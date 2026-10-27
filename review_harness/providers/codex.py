"""OpenAI Codex CLI (`codex exec`) on a ChatGPT subscription login, for reviewers from outside Anthropic.

The login is the `auth.json` that `codex login` writes (ChatGPT sign-in, file-based credential store), kept in the
repo secret named by the reviewer's `secret` (CODEX_AUTH_JSON). Each run seeds it into a private CODEX_HOME. Codex
refreshes the tokens in place about every 8 days; when the file changes, the adapter writes the new version to
$CODEX_AUTH_OUT and the workflow saves it back to the secret, so the next run starts from the fresh tokens.
OpenAI documents this as an advanced path for trusted private repos ("CI/CD auth", developers.openai.com/codex/auth/
ci-cd-auth, which redirects to learn.chatgpt.com/docs/auth/ci-cd-auth; also "Non-interactive mode": seed auth.json from
secure storage, let Codex refresh it on the runner, persist the updated file between runs).

The reviewer works in a disposable copy of the checkout, in Codex's workspace-write sandbox with the network off: it
can read files and run the tests (which need a writable temp folder), and anything it writes is thrown away with the
copy. It never asks for approval. It does not load AGENTS.md project docs (a PR could otherwise instruct its own
reviewer), and its web search is limited to OpenAI's cached index (no live page visits), matching the Claude
reviewer's search-but-no-fetch rule in REVIEW.md. Its environment holds no GitHub token, Claude token or API key; the workflow also
keeps those out of the review step and removes the git credential before it (Codex can read any file the runner
user can, including other processes' environments). As the author (mode "respond", `/respond` on Codex-built PRs) it instead edits the PR's checkout in place, with no
web search; .git stays read-only in the sandbox, so it cannot commit, and respond.py undoes edits to the review
machinery. Its final answer is bound to the review schema with
--output-schema; the harness validates it again afterwards.
"""

import copy
import re
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from ..config import ROOT, load_config, schema_path
from .base import Completion, Provider
from .claude_code import flatten, kill_tree

PASS_ENV = ("PATH", "LANG", "LC_ALL", "TMPDIR", "CI", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
            "https_proxy", "http_proxy", "no_proxy", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS")
KEEP = {"type", "properties", "required", "additionalProperties", "items", "enum", "description"}
TEST_HINT = ("You are working in a disposable copy of the repository with no network. You may run the tests "
             "(`python -m pytest -q`, or a single file) and git commands to check findings. Anything you write is "
             "thrown away and does not count: do not edit files to fix problems, report them as findings.")
AUTH_FAILURE = re.compile(r"\b401\b|unauthori[sz]ed|refresh[ _]token|not logged in|log in again|sign in again", re.I)
MIN_ATTEMPT_SECONDS = 60          # a retry with less time than this would only time out
RESPOND_HINT = ("You are working in the pull request's checkout with no network. Edit files to apply the fixes you "
                "accept and run the tests. You cannot commit or push (.git is read-only), and edits to the review "
                "machinery are undone; the workflow commits your changes and opens the pull request.")
LIMIT_FAILURE = re.compile(r"usage limit|rate limit|\b429\b|quota", re.I)


# ---- schema: Codex binds the final answer with OpenAI structured outputs, which need a strict schema ------------------

def strict_schema(schema: dict) -> dict:
    """Every property required (optional ones made nullable), refs inlined, only widely supported keywords kept.

    The harness's own validator still applies the full schema (patterns, lengths, ranges) after nulls are dropped.
    """
    defs = schema.get("$defs", {})

    def walk(node: dict) -> dict:
        if "$ref" in node:
            node = defs[node["$ref"].split("/")[-1]]
        node = copy.deepcopy(node)
        if "const" in node:
            node["enum"] = [node.pop("const")]
            node.setdefault("type", "integer" if isinstance(node["enum"][0], int) else "string")
        out = {k: v for k, v in node.items() if k in KEEP}
        if "enum" in out and "type" not in out:
            out["type"] = "string"
        if out.get("type") == "object" or "properties" in out:
            props = {k: walk(v) for k, v in node.get("properties", {}).items()}
            required = set(node.get("required", []))
            for k, v in props.items():
                if k not in required:                       # optional -> required but may be null
                    v["type"] = [v["type"], "null"] if isinstance(v.get("type"), str) else v.get("type")
                    if "enum" in v:
                        v["enum"] = v["enum"] + [None]
            out.update(type="object", properties=props, required=list(props), additionalProperties=False)
        if "items" in out:
            out["items"] = walk(node["items"])
        return out

    return walk(schema)


def strip_nulls(value):
    """Drop keys whose value is null (the strict schema's stand-in for 'absent')."""
    if isinstance(value, dict):
        return {k: strip_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [strip_nulls(v) for v in value]
    return value


# ---- login file --------------------------------------------------------------------------------------------------------

def secrets_in(auth: dict) -> list[str]:
    """Every long string in auth.json (access, refresh and id tokens, account ids), for scrubbing output."""
    found = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str) and len(v) >= 20:
            found.append(v)
    walk(auth)
    return sorted(set(found), key=len, reverse=True)


def scrub(text: str, secrets: list[str]) -> str:
    for s in secrets:
        text = text.replace(s, "[redacted]")
    return text


def explain(messages: list[str], stderr: str, returncode, timed_out: bool = False, failed: list[str] | None = None) -> str:
    """One readable line for the failure comment on the PR. The diagnosis comes from the last turn.failed message
    (or, without one, the last error event): earlier error events are often transient reconnects ("rate limit,
    reconnecting") and must not label a later, different failure. stderr is detail only, never matched."""
    detail = " ".join(messages[-3:] + [stderr[-300:]]).strip()[:400]
    if timed_out:
        return f"Codex timed out without a final answer. Detail: {detail}"
    events = (failed or messages or [""])[-1]
    if AUTH_FAILURE.search(events):
        return ("Codex could not use the saved ChatGPT login (expired, revoked or rotated by another run). Re-seed "
                "it: run `codex login` on a computer and save ~/.codex/auth.json as the CODEX_AUTH_JSON secret. "
                f"Detail: {detail}")
    if LIMIT_FAILURE.search(events):
        return ("The ChatGPT plan's Codex usage limit was reached; try again after it resets (`/status` in the "
                f"Codex CLI shows when). Detail: {detail}")
    return f"Codex exited with {returncode} without a final answer. Detail: {detail}"


# ---- running -----------------------------------------------------------------------------------------------------------

def describe(item: dict) -> str | None:
    kind = item.get("type")
    if kind == "command_execution":
        return f"Run `{' '.join(str(item.get('command', '')).split())[:100]}`"
    if kind == "web_search":                 # the query is shown so REVIEW.md rule 8 can be checked afterwards
        query = " ".join(str(item.get("query") or "").split())[:80]
        return f"Search the web for `{query}`" if query else "Search the web"
    if kind == "mcp_tool_call":
        return f"Tool `{item.get('tool', '?')}`"
    if kind == "file_change":
        return "Edit files in the disposable copy (discarded)"
    return None


def build_command(binary: str, model: str, effort: str | None, schema_file: str, last_file: str, work_dir: str,
                  mode: str = "review", extra_dirs: tuple[str, ...] = ()) -> list[str]:
    """review: cached web search, works in a disposable copy. respond (the author): no web search, edits the PR
    checkout in place; extra_dirs (its temp folder) are writable too."""
    if mode not in ("review", "respond"):
        raise ValueError(f"unknown mode {mode!r}")
    cmd = [binary, "exec", "--json", "--ephemeral",
           "-m", model,
           "-s", "workspace-write",
           "-c", "sandbox_workspace_write.network_access=false",
           "-C", work_dir,
           "--output-schema", schema_file,
           "-o", last_file,
           "-c", "approval_policy=\"never\"",
           "-c", "cli_auth_credentials_store=\"file\"",
           "-c", "project_doc_max_bytes=0",            # ignore AGENTS.md in the reviewed tree: a PR can't brief its reviewer
           "-c", "web_search=\"cached\"" if mode == "review" else "web_search=\"disabled\""]
    for d in extra_dirs:
        cmd += ["--add-dir", d]
    if effort:
        cmd += ["-c", f"model_reasoning_effort=\"{effort}\""]
    return cmd + ["-"]                                   # the prompt comes on stdin


def codex_env(home: Path, tmp: Path, environ=os.environ) -> dict:
    """Only what the CLI needs. No GitHub token, Claude token, API key, or the login secret itself."""
    env = {k: environ[k] for k in PASS_ENV if k in environ and k != "TMPDIR"}
    env.update(HOME=str(home), CODEX_HOME=str(home), TMPDIR=str(tmp), PYTHONDONTWRITEBYTECODE="1")
    return env


def make_workspace(src: Path, parent: Path) -> Path:
    """A throwaway copy of the checkout for the reviewer to work (and run tests) in, without git credentials."""
    dst = parent / "work"
    shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    if (dst / ".git").is_dir():
        subprocess.run(["git", "-C", str(dst), "config", "--local", "--unset-all", "http.https://github.com/.extraheader"],
                       capture_output=True)
    (dst / ".tmp").mkdir(exist_ok=True)
    if (dst / ".git" / "info").is_dir() or (dst / ".git").is_dir():
        info = dst / ".git" / "info"
        info.mkdir(exist_ok=True)
        with open(info / "exclude", "a") as fh:     # keep `git status` clean: the temp folder is not part of the PR
            fh.write("\n/.tmp/\n")
    return dst


class CodexProvider(Provider):
    def __init__(self, reviewer: dict, cwd: Path = ROOT, work_dir: Path | None = None, binary: str = "codex",
                 environ=os.environ, mode: str = "review", schema: dict | None = None):
        """reviewer: a reviewer or author entry of review/config.yaml. mode "respond" makes it the author."""
        self.model, self.effort = reviewer["model"], reviewer.get("reasoning_effort")
        raw = environ.get(reviewer["secret"], "").strip()
        if not raw:
            raise RuntimeError(f"environment variable {reviewer['secret']} is not set (the saved Codex login)")
        try:
            self.auth = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(f"{reviewer['secret']} is not valid JSON: save the whole ~/.codex/auth.json file") from None
        if shutil.which(binary) is None:
            raise RuntimeError(f"the Codex CLI ({binary!r}) is not installed")
        cfg = load_config(cwd)
        limits = cfg["limits"]                 # Codex has no turn cap, so time is its only bound
        # A budget for the whole run, shared by the harness's retry: two full attempts plus setup could run past
        # the job limit and cancel the step that saves a refreshed login (PR87-4-F3).
        key = "respond_codex_timeout_minutes" if mode == "respond" else "codex_timeout_minutes"
        self.timeout = 60 * limits.get(key, limits.get("agent_timeout_minutes", 25))
        self.deadline, self.mode = None, mode
        build_command("x", "m", None, "s", "o", "w", mode)        # rejects an unknown mode early
        self.schema = schema or json.loads(schema_path(cwd, cfg).read_text())
        self.binary, self.cwd, self.environ = binary, Path(work_dir or cwd), environ
        self.out_path = environ.get("CODEX_AUTH_OUT")
        self.on_step = None

    def complete(self, system: str, messages: list[dict], max_output_tokens: int) -> Completion:
        retry = self.deadline is not None
        if not retry:
            self.deadline = time.monotonic() + self.timeout
        budget = self.deadline - time.monotonic()
        if retry and budget < MIN_ATTEMPT_SECONDS:
            raise RuntimeError(f"Codex has used its {self.timeout // 60}-minute budget for this review "
                               "(codex_timeout_minutes, shared by the retry); no time is left for another attempt.")
        seeded_secrets = secrets_in(self.auth)
        # Codex declines to set up its helpers under /tmp, so use the runner's temp folder when there is one.
        with tempfile.TemporaryDirectory(prefix="codex-home-", dir=self.environ.get("RUNNER_TEMP")) as home_dir, \
                tempfile.TemporaryDirectory(prefix="codex-work-", dir=self.environ.get("RUNNER_TEMP")) as work_parent:
            home = Path(home_dir)
            seeded = json.dumps(self.auth, indent=2)
            auth_file = home / "auth.json"
            auth_file.write_text(seeded)
            auth_file.chmod(0o600)
            (home / "config.toml").write_text('cli_auth_credentials_store = "file"\n')
            schema_file, last_file = home / "schema.json", home / "last.json"
            schema_file.write_text(json.dumps(strict_schema(self.schema)))
            if self.mode == "review":
                work, extra, hint = make_workspace(self.cwd, Path(work_parent)), (), TEST_HINT
                tmp = work / ".tmp"
            else:                                    # the author edits the real checkout; temp files stay outside it
                work, tmp, hint = self.cwd, Path(work_parent) / "tmp", RESPOND_HINT
                tmp.mkdir()
                extra = (str(tmp),)

            def current_secrets() -> list[str]:
                """Seeded tokens plus any Codex has refreshed during the run."""
                try:
                    now = secrets_in(json.loads(auth_file.read_text()))
                except (OSError, json.JSONDecodeError):
                    now = []
                return sorted(set(seeded_secrets) | set(now), key=len, reverse=True)

            prompt = f"# Instructions\n\n{system}\n\n{hint}\n\n# Task\n\n{flatten(messages)}"
            try:
                result = self._run(build_command(self.binary, self.model, self.effort, str(schema_file),
                                                 str(last_file), str(work), self.mode, extra),
                                   prompt, codex_env(home, tmp, self.environ), current_secrets, work,
                                   budget)
            finally:
                note = self._save_refreshed(auth_file, seeded)
            secrets = current_secrets()
            text = last_file.read_text().strip() if last_file.exists() else ""
        if not text:
            raise RuntimeError(scrub(explain(result["errors"], result["stderr"], result["returncode"],
                                             result["timed_out"], result["failed"]) + note, secrets))
        try:
            text = json.dumps(strip_nulls(json.loads(text)))
        except json.JSONDecodeError:
            pass                                          # let the harness report it and retry
        return Completion(scrub(text, secrets), result["input_tokens"], result["output_tokens"])

    def _save_refreshed(self, auth_file: Path, seeded: str) -> str:
        """If Codex refreshed the login, hand the new file to the workflow (and use it for a retry in this run).
        Returns a note for the failure message ("" normally). A file cut off mid-write (the timeout killed Codex while
        it was saving a refresh) is left alone, so the real failure is still the one reported."""
        try:
            now = auth_file.read_text()
            parsed = json.loads(now) if now.strip() else None
        except OSError:
            return ""
        except json.JSONDecodeError:
            return (" The login file was left half-written, so it was not saved back; if the next run reports an "
                    "expired login, re-seed CODEX_AUTH_JSON.")
        if parsed is not None and parsed != json.loads(seeded):
            self.auth = parsed
            if self.out_path:
                Path(self.out_path).write_text(now)
                os.chmod(self.out_path, 0o600)
        return ""

    def _run(self, cmd: list[str], prompt: str, env: dict, current_secrets, cwd: Path, budget: float) -> dict:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, cwd=cwd, env=env, start_new_session=True)
        killed = threading.Event()

        def on_timeout():
            killed.set()                         # set before the kill, so the result never races the timer thread
            kill_tree(proc)
        timer = threading.Timer(budget, on_timeout)
        timer.start()
        stderr: list[str] = []
        reader = threading.Thread(target=lambda: stderr.append(proc.stderr.read()), daemon=True)
        reader.start()
        errors, failed, tokens_in, tokens_out = [], [], 0, 0
        try:
            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
            except BrokenPipeError:
                pass                     # the CLI exited early (bad flag, broken install): its stderr says why
            for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = ev.get("type")
                if kind == "item.started" and self.on_step:
                    text = describe(ev.get("item") or {})
                    if text:
                        try:
                            self.on_step(scrub(text, current_secrets()))
                        except Exception:  # noqa: BLE001 - progress is cosmetic
                            pass
                elif kind == "turn.completed":
                    usage = ev.get("usage") or {}
                    tokens_in += int(usage.get("input_tokens", 0) or 0)
                    tokens_out += int(usage.get("output_tokens", 0) or 0)
                elif kind == "turn.failed":
                    failed.append(str((ev.get("error") or {}).get("message", "turn failed")))
                    errors.append(failed[-1])
                elif kind == "error":
                    errors.append(str(ev.get("message", "")))      # often transient ("Reconnecting...")
            proc.wait()
            reader.join(timeout=5)
        finally:
            timed_out = killed.is_set()
            timer.cancel()
        return {"errors": errors, "failed": failed, "stderr": "".join(stderr), "returncode": proc.returncode, "timed_out": timed_out,
                "input_tokens": tokens_in, "output_tokens": tokens_out}
