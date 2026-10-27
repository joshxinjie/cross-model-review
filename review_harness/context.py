"""Build the context pack a reviewer reads: which files, in what order, within a token budget."""

import fnmatch
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".cfg", ".ini"}
MAX_FILE_BYTES = 200_000
MAX_DEPENDENTS = 10
CHARS_PER_TOKEN = 4          # rough; good enough for a budget, not for billing

# Lines that would tell the reviewer which model wrote the work (independence rule 1). Best effort only: the
# repo's own docs mention Claude in places, so blindness is partial.
ATTRIBUTION = re.compile(
    r"^.*(Co-Authored-By:|Claude-Session:|Generated with \[Claude Code\]|claude\.ai/code/session_).*$\n?",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class Item:
    label: str           # path, or a name such as "DIFF"
    text: str
    priority: int        # 0 kept first; higher numbers are dropped first when over budget

    @property
    def tokens(self) -> int:
        return len(self.text) // CHARS_PER_TOKEN + 1


def sanitize(text: str) -> str:
    return ATTRIBUTION.sub("", text)


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + 1


def matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern) or fnmatch.fnmatch(path, pattern + "*")
    return fnmatch.fnmatch(path, pattern)


def readable(root: Path, rel: str, exclude: list[str]) -> str | None:
    p = root / rel
    if not p.is_file() or p.suffix not in TEXT_SUFFIXES or any(matches(rel, x) for x in exclude):
        return None
    if p.stat().st_size > MAX_FILE_BYTES:
        return p.read_text(errors="replace")[:MAX_FILE_BYTES] + "\n[... truncated by the review harness ...]\n"
    return p.read_text(errors="replace")


def pathspec_excludes(exclude: list[str]) -> list[str]:
    """Config exclude patterns as git pathspecs ('data/raw/' -> ':(exclude,glob)data/raw/**')."""
    out = []
    for x in exclude:
        pattern = x + "**" if x.endswith("/") else x
        out.append(f":(exclude,glob){pattern}")
    return out


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def module_names(rel: str) -> set[str]:
    """Dotted names a file can be imported as: every suffix of its path with at least two parts (any suffix for a
    package's __init__.py)
    ('src/pkg/mod.py' -> 'src.pkg.mod', 'pkg.mod'). A bare
    name ('context') is left out: it would match unrelated modules that share the stem."""
    parts = list(Path(rel).with_suffix("").parts)
    if parts and parts[-1] == "__init__":    # a package: its own name is specific enough to match alone
        parts = parts[:-1]
        return {".".join(parts[k:]) for k in range(len(parts))}
    return {".".join(parts[k:]) for k in range(len(parts) - 1)}


def imported_targets(rel: str, text: str) -> tuple[set[str], set[str]]:
    """(dotted names, repo paths) a Python file imports, from its syntax tree. Covers `import a.b`, `import a.b as
    x`, `from a import b` (b may be a module), and relative imports (resolved to paths). A bare sibling import
    (`import core` next to core.py) is resolved to a path in the same folder."""
    import ast
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set(), set()
    names, paths = set(), set()
    here = Path(rel).parent

    def as_paths(base: Path, dotted: str):
        stem = base.joinpath(*dotted.split(".")) if dotted else base
        return {stem.with_suffix(".py").as_posix(), (stem / "__init__.py").as_posix()}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name)
                if "." not in a.name:
                    paths |= as_paths(here, a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:                       # relative: resolve against this file's package
                base = here
                for _ in range(node.level - 1):
                    base = base.parent
                paths |= as_paths(base, node.module or "")
                for a in node.names:
                    paths |= as_paths(base, ".".join(x for x in (node.module, a.name) if x))
            elif node.module:
                names.add(node.module)
                names |= {f"{node.module}.{a.name}" for a in node.names}
                if "." not in node.module:
                    paths |= as_paths(here, node.module)
    return names, paths


def find_dependents(root: Path, changed: list[str], limit: int = MAX_DEPENDENTS) -> list[str]:
    """Python files that import a changed module, or name a changed data file (e.g. read its CSV output).

    Imports are read from the syntax tree, so package imports, aliases and relative imports count, and a module is
    matched by its package path, not just its name. Documents are not traced: code doesn't depend on them in a way
    a reviewer needs.
    """
    mods, mod_paths, data = set(), set(), []
    for rel in changed:
        p = Path(rel)
        if p.suffix == ".py":                # package initialisers too (PROJ-2026-10-26-2-F4)
            mods |= module_names(rel)
            mod_paths.add(p.as_posix())
        elif p.suffix in {".csv", ".json", ".parquet", ".yaml", ".yml", ".xlsx", ".txt"}:
            data.append(re.compile(re.escape(p.name)))
    found = []
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root).as_posix()
        if rel in changed or rel.startswith((".git/", "data/raw/", "data/vintages/")):
            continue
        try:
            text = py.read_text(errors="replace")
        except OSError:
            continue
        hit = any(n.search(text) for n in data)
        if not hit and mod_paths:
            names, paths = imported_targets(rel, text)
            hit = bool(names & mods or paths & mod_paths)
        if hit:
            found.append(rel)
            if len(found) >= limit:
                break
    return found


# Always-included files that belong to the review process, not to the work under review (config.protected_paths):
# read from the project's trusted checkout (main), so a pull request cannot rewrite the decision log the reviewer is
# told to respect.
def always_source(rel: str, root: Path, trusted: Path | None, cfg: dict) -> Path:
    from .config import protected_paths
    return trusted if trusted is not None and rel.startswith(tuple(protected_paths(cfg))) else root


def fit_to_budget(items: list[Item], budget: int) -> tuple[list[Item], list[str]]:
    """Drop the lowest-priority, largest items until the pack fits; return kept items and dropped labels."""
    kept = sorted(items, key=lambda it: it.priority)
    dropped = []
    while sum(it.tokens for it in kept) > budget and kept:
        worst = max(range(len(kept)), key=lambda k: (kept[k].priority, kept[k].tokens))
        if kept[worst].priority == 0:
            # Never drop instructions or the diff; truncate the largest priority-0 item instead.
            big = max(range(len(kept)), key=lambda k: kept[k].tokens)
            excess = sum(it.tokens for it in kept) - budget
            keep_chars = max(2000, (kept[big].tokens - excess) * CHARS_PER_TOKEN)
            kept[big] = Item(kept[big].label, kept[big].text[:keep_chars]
                             + "\n[... truncated by the review harness to fit the budget ...]\n", 0)
            dropped.append(f"{kept[big].label} (truncated)")
            break
        dropped.append(kept.pop(worst).label)
    return kept, dropped


def render(items: list[Item]) -> str:
    return "\n".join(f"===== {it.label} =====\n{it.text.rstrip()}\n" for it in items)


def build_pr_pack(root: Path, cfg: dict, base: str, head: str = "HEAD",
                  title: str = "", body: str = "", trusted: Path | None = None) -> dict:
    """root is an unmodified checkout of the PR head: the diff, changed files and dependents all come from it, so the
    reviewer sees one revision (PROJ-2026-10-26-F1). trusted is the harness checkout (main) for the review process's
    own always-included files."""
    ctx = cfg["context"]["pr"]
    exclude = cfg["context"]["project"]["exclude"]
    full_stat = git(root, "diff", "--numstat", f"{base}...{head}")
    diff = git(root, "diff", "--unified=3", f"{base}...{head}", "--", ".", *pathspec_excludes(exclude))
    omitted = [line.split("\t")[-1] for line in full_stat.splitlines()
               if line and any(matches(line.split("\t")[-1], x) for x in exclude)]
    if omitted:
        diff += ("\n[review harness: data and generated output files changed but left out of this diff: "
                 + ", ".join(omitted[:40]) + (" …" if len(omitted) > 40 else "") + "]\n")
    changed = [p for p in git(root, "diff", "--name-only", "--diff-filter=d", f"{base}...{head}").split() if p]
    items = [Item("PULL REQUEST", sanitize(f"Title: {title}\n\n{body}".strip()), 0),
             Item("DIFF", diff, 0)]
    for rel in ctx["always"]:
        if rel != cfg["instructions"] and (t := readable(always_source(rel, root, trusted, cfg), rel, [])) is not None:
            items.append(Item(rel, t, 0))           # (instructions go in the system prompt)
    for rel in changed:
        if rel in ctx["always"]:
            continue
        if (t := readable(root, rel, exclude)) is not None:
            items.append(Item(rel, t, 1))
    deps = find_dependents(root, changed) if ctx.get("include_dependents") else []
    for rel in deps:
        if (t := readable(root, rel, exclude)) is not None:
            items.append(Item(rel, t, 2))
    kept, dropped = fit_to_budget(items, cfg["limits"]["max_input_tokens"]["pr"])
    return {"scope": "pr", "text": render(kept), "diff": diff, "changed": changed, "dependents": deps,
            "files": [it.label for it in kept], "dropped": dropped,
            "tokens": sum(it.tokens for it in kept)}


def build_project_pack(root: Path, cfg: dict, areas: list[str] | None = None, trusted: Path | None = None) -> dict:
    ctx = cfg["context"]["project"]
    exclude = ctx["exclude"]
    items = []
    for rel in ctx["always"]:
        if rel != cfg["instructions"] and (t := readable(always_source(rel, root, trusted, cfg), rel, [])) is not None:
            items.append(Item(rel, t, 0))
    seen = set(ctx["always"])
    for k, area in enumerate(areas or ctx["default_areas"]):
        hits = [root / area] if (root / area).is_file() else sorted((root / area.rstrip("/")).rglob("*")) \
            if (root / area.rstrip("/")).is_dir() else sorted(root.glob(area))
        for p in hits:
            rel = p.relative_to(root).as_posix()
            if rel in seen:
                continue
            if (t := readable(root, rel, exclude)) is not None:
                items.append(Item(rel, t, 1 + k))     # earlier areas matter more
                seen.add(rel)
    kept, dropped = fit_to_budget(items, cfg["limits"]["max_input_tokens"]["project"])
    return {"scope": "project", "text": render(kept), "diff": "", "changed": [], "dependents": [],
            "files": [it.label for it in kept], "dropped": dropped,
            "tokens": sum(it.tokens for it in kept)}
