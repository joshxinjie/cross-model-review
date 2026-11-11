"""Hash-pinned adapter for an owner-supplied official public notebook export.

Never downloads or submits. Source is read/hash-checked before execution.
Use the official per-puzzle evaluator serially: no pool or details-file side
effects. Invalid/missing puzzles retain the official grid penalty and reasons.
"""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import types
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / 'metric.lock.json').read_text())


def load_official(path):
    pins = [line.split('==') for line in (ROOT / 'requirements.lock').read_text().splitlines() if line]
    for package, version in pins:
        if importlib.metadata.version(package) != version:
            raise ValueError(f'official adapter requires {package}=={version}')
    source = Path(path).read_bytes()
    if hashlib.sha256(source).hexdigest() != LOCK['source_sha256']:
        raise ValueError('official metric source hash mismatch')
    name = '_sis_pinned_official_metric'
    module = types.ModuleType(name)
    sys.modules[name] = module
    try:
        exec(compile(source, str(path), 'exec'), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def evaluate(module, text, puzzle_ns):
    from .packing import puzzle_number
    ns = sorted(set(puzzle_ns))
    for n in ns:
        puzzle_number(n)
    puzzles = module._parse_submission_csv(text)
    results = []
    for n in ns:
        if n in puzzles:
            result = module.evaluate_single_puzzle(n, puzzles[n])
        else:
            result = (n, module.infeasible_score(n), None, 'missing from submission')
        results.append(result)
    return sum(r[1] for r in results), results
