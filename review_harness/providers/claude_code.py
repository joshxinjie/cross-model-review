"""Claude Code CLI in print mode, authenticated with a Claude subscription token (CLAUDE_CODE_OAUTH_TOKEN).

Uses subscription usage instead of API credits. Two modes:
- "review": the reviewer can look things up and run the tests; read-only tools plus a short list of safe commands.
- "respond": the author can also edit files and run Python to apply fixes, but never the review machinery itself
  (the project's protected paths, review/config.yaml), and never commit or push: the workflow does that, as a pull request.
Neither mode gets the GitHub token. The reviewer may search the web (to check and cite outside facts, per REVIEW.md)
but not fetch pages; the author gets neither.
"""

import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from ..config import ROOT, agent_env_extra, load_config, protected_paths, schema_path
from .base import Completion, Provider

READ_TOOLS = ["Read", "Grep", "Glob"]
TEST_COMMANDS = ["python -m pytest", "python3 -m pytest", "pytest"]
SAFE_COMMANDS = ["Bash(git diff *)", "Bash(git log *)", "Bash(git show *)", "Bash(ls *)",
                 *(f"Bash({c} *)" for c in TEST_COMMANDS)]
EDIT_TOOLS = ["Edit", "Write"]
RESPOND_COMMANDS = ["Bash(git status *)", "Bash(python *)", "Bash(python3 *)"]
# The author may not change how reviews work or what the reviewer decided (config.protected_paths); respond.py also
# reverts any such change.


MIN_ATTEMPT_SECONDS = 60          # a retry with less time than this would only time out
PASS_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "CI")


def kill_tree(proc) -> None:
    """Kill the CLI and everything it started. npm launchers start the real binary as a child, so killing only the
    launcher leaves the child holding the output pipe open and the reader waiting forever."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def agent_env(secret: str, environ=os.environ, extra: dict | None = None) -> dict:
    """Only what the CLI needs, plus the subscription token. Never the GitHub token or an API key: an API key would
    switch Claude Code to API billing, and the agent has no business with GitHub write access."""
    env = {k: environ[k] for k in PASS_ENV if k in environ}
    env.update(extra or {})                       # the project's agent_env settings (never credentials)
    # A token copied from a terminal can pick up a line break where the terminal wrapped it; tokens never contain
    # whitespace, so drop any.
    env[secret] = "".join(environ[secret].split())
    return env


def cli_schema(schema: dict) -> dict:
    """The CLI's validator rejects meta-schema URLs; the schema itself is unchanged."""
    return {k: v for k, v in schema.items() if k not in ("$schema", "$id")}


def env_prefixed_rules(commands: list[str], settings: dict | None) -> list[str]:
    """The same commands written with the project's agent_env settings in front (`TRADELAB_PROVIDER=synthetic python
    -m pytest -q`). The settings are already in the agent's environment, but models copy the repo's documented
    command line, and Claude Code matches rules on the command's text: the prefixed form was denied, so reviewers
    reported that they could not run the tests (trading-lab #32, #35, #37)."""
    if not settings:
        return []
    prefixes = [f"{k}={v}" for k, v in settings.items()]
    if len(prefixes) > 1:
        prefixes.append(" ".join(prefixes))
    return [f"Bash({p} {c[len('Bash('):]}" for p in prefixes for c in commands]


def command_hint(mode: str, settings: dict | None) -> str:
    """Appended to the system prompt: which command lines run, so the agent doesn't spend turns on denied ones."""
    tests = "`python -m pytest -q` (or a file, or `-k`)"
    have = (" These settings are already in your environment: " + ", ".join(f"`{k}={v}`" for k, v in settings.items())
            + "; do not put them in front of commands.") if settings else ""
    if mode == "respond":
        return ("\n\n## Running commands\n\nRun the tests with " + tests + "; you may also run `python ...` scripts and "
                "read-only git commands (`git diff`, `git log`, `git show`, `git status`)." + have + " You cannot "
                "commit, push, reset, check out or delete files; the workflow commits your edits.\n")
    return ("\n\n## Running commands\n\nYou may run the tests with " + tests + " and read-only git commands (`git diff`, "
            "`git log`, `git show`), plus `ls`. Anything else is denied without asking." + have
            + " If a command is denied, say what you could not run; do not report that the tests fail.\n")


def protected_rules(protected) -> list[str]:
    rules = []
    for path in protected:
        target = f"./{path}**" if path.endswith("/") else f"./{path}"
        rules += [f"Edit({target})", f"Write({target})"]
    return rules


def build_command(model: str, system_file: str, schema: dict, max_turns: int, mode: str = "review",
                  protected=(".github/", "review/", "reviews/", "REVIEW.md"), settings: dict | None = None) -> list[str]:
    tests = [f"Bash({c} *)" for c in TEST_COMMANDS]
    if mode == "review":
        tools = READ_TOOLS + ["Bash", "WebSearch"]
        allowed = READ_TOOLS + SAFE_COMMANDS + env_prefixed_rules(tests, settings) + ["WebSearch"]
        denied = ["Edit", "Write", "NotebookEdit", "WebFetch"]
    elif mode == "respond":
        tools = READ_TOOLS + EDIT_TOOLS + ["Bash"]
        allowed = (READ_TOOLS + EDIT_TOOLS + SAFE_COMMANDS + RESPOND_COMMANDS
                   + env_prefixed_rules(tests + RESPOND_COMMANDS[1:], settings))
        denied = ["NotebookEdit", "WebSearch", "WebFetch", "Bash(git commit *)", "Bash(git push *)", "Bash(git reset *)",
                  "Bash(git checkout *)", "Bash(rm *)", *protected_rules(protected)]
    else:
        raise ValueError(f"unknown mode {mode!r}")
    return ["claude", "-p",
            "--model", model,
            "--output-format", "json",
            "--append-system-prompt-file", system_file,
            "--json-schema", json.dumps(cli_schema(schema)),
            "--tools", ",".join(tools),
            "--allowedTools", *allowed,
            "--disallowedTools", *denied, "mcp__*",
            "--permission-prompts", "none",       # anything not allowed above is denied, never waited on
            "--max-turns", str(max_turns),
            "--no-session-persistence"]


def flatten(messages: list[dict]) -> str:
    """The CLI takes one prompt; fold a retry conversation into it."""
    if len(messages) == 1:
        return messages[0]["content"]
    parts = [messages[0]["content"]]
    for m in messages[1:]:
        label = "Your previous reply" if m["role"] == "assistant" else "Feedback"
        parts.append(f"\n\n===== {label} =====\n{m['content']}")
    return "".join(parts)


def parse_output(stdout: str) -> Completion:
    """Read the CLI's JSON result; prefer the schema-validated object when present."""
    data = json.loads(stdout)
    if data.get("is_error"):
        raise RuntimeError(f"Claude Code reported an error ({data.get('subtype', 'unknown')}): "
                           f"{str(data.get('result', ''))[:400]}")
    structured = data.get("structured_output")
    text = json.dumps(structured) if isinstance(structured, dict) else str(data.get("result", ""))
    usage = data.get("usage") or {}
    tokens_in = sum(int(usage.get(k, 0) or 0) for k in
                    ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return Completion(text, tokens_in, int(usage.get("output_tokens", 0) or 0))


def describe(name: str, args: dict, work_dir: Path) -> str | None:
    """One line for the live progress comment, e.g. 'Read plans/live-test.md'. None for steps not worth showing."""
    def rel(path: str) -> str:
        try:
            return str(Path(path).resolve().relative_to(work_dir.resolve()))
        except (ValueError, OSError):
            return path
    if name in ("Read", "Edit", "Write"):
        return f"{name} `{rel(args.get('file_path', '?'))}`"
    if name == "Grep":
        return f"Search for `{str(args.get('pattern', ''))[:60]}`"
    if name == "Glob":
        return f"List `{str(args.get('pattern', ''))[:60]}`"
    if name == "Bash":
        return f"Run `{' '.join(str(args.get('command', '')).split())[:100]}`"
    if name == "WebSearch":
        return f"Search the web for `{str(args.get('query', ''))[:80]}`"
    if name == "StructuredOutput":
        return "Write the final answer"
    return f"{name}"


def stream(cmd: list[str], prompt: str, cwd: Path, env: dict, timeout: float, on_step=None) -> dict:
    """Run the CLI with stream-json output; report each tool call to on_step; return the final result event."""
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            cwd=cwd, env=env, start_new_session=True)
    timer = threading.Timer(timeout, kill_tree, [proc])
    timer.start()
    result, stderr = None, []
    reader = threading.Thread(target=lambda: stderr.append(proc.stderr.read()), daemon=True)
    reader.start()
    try:
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except BrokenPipeError:
            pass                         # the CLI exited early: its stderr (reported below) says why
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "assistant" and on_step:
                for block in ev.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        text = describe(block.get("name", ""), block.get("input") or {}, cwd)
                        if text:
                            try:
                                on_step(text)
                            except Exception:  # noqa: BLE001 - progress is cosmetic; never break the run
                                pass
            elif ev.get("type") == "result":
                result = ev
        proc.wait()
        reader.join(timeout=5)
    finally:
        timer.cancel()
    if result is None:
        why = "timed out" if proc.returncode in (-9, 137) else f"exited with {proc.returncode}"
        raise RuntimeError(f"Claude Code {why} without a result: {''.join(stderr)[-400:]}")
    return result


class ClaudeCodeProvider(Provider):
    """config is read from the harness root (main); the agent works in work_dir (the PR checkout, by default the same)."""

    def __init__(self, reviewer: dict, run=subprocess.run, cwd: Path = ROOT, mode: str = "review",
                 work_dir: Path | None = None, schema: dict | None = None):
        self.model = reviewer["model"]
        if not os.environ.get(reviewer["secret"]):
            raise RuntimeError(f"environment variable {reviewer['secret']} is not set")
        if run is subprocess.run and not shutil.which("claude"):
            raise RuntimeError("the Claude Code CLI ('claude') is not installed")
        cfg = load_config(cwd)
        limits = cfg["limits"]
        prefix = "respond_" if mode == "respond" else ""
        self.max_turns = limits.get(f"{prefix}max_agent_turns", limits.get("max_agent_turns", 40))
        self.timeout = 60 * limits.get(f"{prefix}agent_timeout_minutes", limits.get("agent_timeout_minutes", 25))
        self.schema = schema or json.loads(schema_path(cwd, cfg).read_text())
        self.protected = protected_paths(cfg)
        self.extra_env = agent_env_extra(cfg)
        self.run, self.cwd, self.secret, self.mode = run, Path(work_dir or cwd), reviewer["secret"], mode
        self.on_step = None          # set to a callable to receive one line per tool call (live progress)
        self.deadline = None         # one time budget for the run, shared by the retry (PROJ-2026-10-26-2-F2)

    def complete(self, system: str, messages: list[dict], max_output_tokens: int) -> Completion:
        retry = self.deadline is not None
        if not retry:
            self.deadline = time.monotonic() + self.timeout
        budget = self.deadline - time.monotonic()
        if retry and budget < MIN_ATTEMPT_SECONDS:
            raise RuntimeError(f"Claude Code has used its {self.timeout // 60}-minute budget for this run (shared "
                               "by the retry); no time is left for another attempt.")
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write(system + command_hint(self.mode, self.extra_env))
            system_file = fh.name
        cmd = build_command(self.model, system_file, self.schema, self.max_turns, self.mode, self.protected,
                            self.extra_env)
        try:
            if self.run is subprocess.run:          # the real CLI: stream, so progress can be shown live
                i = cmd.index("--output-format")
                cmd[i + 1: i + 2] = ["stream-json", "--verbose"]
                return parse_output(json.dumps(stream(cmd, flatten(messages), self.cwd, agent_env(self.secret, extra=self.extra_env),
                                                      budget, self.on_step)))
            proc = self.run(cmd, input=flatten(messages), capture_output=True, text=True, cwd=self.cwd,
                            timeout=budget, env=agent_env(self.secret, extra=self.extra_env))
        finally:
            os.unlink(system_file)
        if proc.returncode != 0 and not proc.stdout.strip().startswith("{"):
            raise RuntimeError(f"Claude Code exited with {proc.returncode}: {(proc.stderr or proc.stdout)[-400:]}")
        return parse_output(proc.stdout)
