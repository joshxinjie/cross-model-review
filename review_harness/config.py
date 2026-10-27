"""Load the project's review/config.yaml and pick a reviewer.

ROOT is the project's trusted checkout (its main branch): REVIEW_PROJECT_ROOT, or the current directory. The
harness code itself lives elsewhere (this repository), so a pull request cannot change how it is reviewed.
"""

import os
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("REVIEW_PROJECT_ROOT") or Path.cwd()).resolve()
PACKAGE = Path(__file__).resolve().parent
DEFAULT_SCHEMAS = {"output_schema": PACKAGE / "schemas" / "review.json",
                   "respond_schema": PACKAGE / "schemas" / "respond.json"}


def load_config(root: Path = ROOT) -> dict:
    cfg = yaml.safe_load((root / "review" / "config.yaml").read_text())
    cfg.setdefault("instructions", "REVIEW.md")
    cfg.setdefault("decision_log", "reviews/decisions.md")
    return cfg


def schema_path(root: Path, cfg: dict, key: str = "output_schema") -> Path:
    """A schema the project names (relative to its root), else the harness's own."""
    rel = cfg.get(key)
    return root / rel if rel else DEFAULT_SCHEMAS[key]


def author_schema_path(root: Path, author: dict) -> Path:
    rel = author.get("output_schema")
    return root / rel if rel else DEFAULT_SCHEMAS["respond_schema"]


def protected_paths(cfg: dict, extras: bool = True) -> list[str]:
    """The review process's own files: the author may not edit them, and the reviewer's copies come from main.
    Always the workflows, review/, the decision log's folder and the reviewer instructions, plus `protected` (a
    path, a folder ending in /, or a glob such as strategies/*/results/)."""
    base = [".github/", "review/", str(Path(cfg["decision_log"]).parent) + "/", cfg["instructions"]]
    out = []
    for p in base + (list(cfg.get("protected", [])) if extras else []):
        if p not in out:
            out.append(p)
    return out


def scope_for(cfg: dict, head_ref: str | None, title: str | None = None) -> list[str] | None:
    """`scopes` in the config: on PRs whose branch starts with one of a scope's branch_prefixes, or whose title starts
    with one of its title_prefixes (case-insensitive), the author may only change files matching its `allowed` globs
    when answering a review (others are undone). Titles matter because a PR's kind need not show in its branch
    (Codex's branches all start codex/). None: no limit beyond the protected paths."""
    ref, name = head_ref or "", (title or "").strip().lower()
    for s in cfg.get("scopes") or []:
        if any(ref.startswith(p) for p in s.get("branch_prefixes", [])) or \
                any(name.startswith(p.lower()) for p in s.get("title_prefixes", [])):
            return list(s.get("allowed", []))
    return None


SECRET_LIKE = ("TOKEN", "KEY", "SECRET", "AUTH", "PASSWORD")


def agent_env_extra(cfg: dict) -> dict:
    """`agent_env` in the config: plain settings the reviewer and author need to run the project's tests (e.g.
    TRADELAB_PROVIDER: synthetic). They are written in the repo, so never credentials; names that look like one are
    refused."""
    out = {}
    for k, v in (cfg.get("agent_env") or {}).items():
        if not str(k).replace("_", "").isalnum() or not str(k)[:1].isalpha() or str(k) != str(k).upper():
            raise ValueError(f"agent_env: {k!r} is not an environment variable name")
        if any(w in str(k) for w in SECRET_LIKE):
            raise ValueError(f"agent_env: {k!r} looks like a credential; credentials belong in repo secrets")
        out[str(k)] = str(v)
    return out


def footer(cfg: dict) -> str:
    """Optional closing line on every comment the harness posts (e.g. a disclaimer)."""
    return cfg.get("footer") or ""


def get_author(cfg: dict, name: str | None = None) -> dict:
    """The named author (default_author if None), with its name added."""
    name = name or cfg["default_author"]
    if name not in cfg["authors"]:
        raise ValueError(f"unknown author {name!r}; known: {', '.join(cfg['authors'])}")
    return dict(cfg["authors"][name], name=name)


FIX_PREFIX = "respond/"


def author_for(cfg: dict, head_ref: str | None) -> dict:
    """Who built a PR, from its branch name; anything unlisted is the default author. A fix PR from `/respond` is on
    respond/<author prefix>pr<N>-<date> (fix_branch_prefix), so it keeps the author that wrote the fixes."""
    ref = head_ref or ""
    if ref.startswith(FIX_PREFIX):
        ref = ref[len(FIX_PREFIX):]
    for name, a in cfg["authors"].items():
        if any(ref.startswith(p) for p in a.get("branch_prefixes", [])):
            return get_author(cfg, name)
    return get_author(cfg)


def fix_branch_prefix(author: dict) -> str:
    """Branch prefix for the author's fix PRs: respond/ for the default author, respond/codex/ for Codex."""
    return FIX_PREFIX + (author.get("branch_prefixes") or [""])[0]


def get_reviewer(cfg: dict, name: str | None = None, author: dict | None = None) -> dict:
    """Return the named reviewer with its name added. Without a name: the author's default reviewer, or the
    top-level default_reviewer when there is no author. Refuses disabled or unpinned reviewers, and any reviewer
    that is the same model as the author (default_author when none is given)."""
    name = name or (author or {}).get("default_reviewer") or cfg["default_reviewer"]
    author = author or get_author(cfg)
    reviewers = cfg["reviewers"]
    if name not in reviewers:
        raise ValueError(f"unknown reviewer {name!r}; known: {', '.join(reviewers)}")
    r = dict(reviewers[name], name=name)
    if not r.get("enabled"):
        raise ValueError(f"reviewer {name!r} is disabled in review/config.yaml")
    if not r.get("model"):
        raise ValueError(f"reviewer {name!r} has no pinned model")
    if r["model"] == author["model"]:
        raise ValueError(f"reviewer {name!r} is the model that built this work ({author['name']}: "
                         f"{author['model']}); reviews must come from a different model")
    return r


def today_sgt() -> str:
    """Review dates are Singapore dates, so file names and the daily limit match the owner's day."""
    import datetime as dt
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
