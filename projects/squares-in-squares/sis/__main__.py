"""Offline experiment runner. All generated artifacts default to private staging."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import time

from .geometry import validate
from .metric import ROOT, LOCK, evaluate, load_official
from .optimize import atomic_json, configuration, digest, optimize
from .packing import deserialize, serialize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--puzzles', default='1:1000', help='inclusive first:last')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--max-steps', type=int, default=100)
    parser.add_argument('--steps-per-call', type=int)
    parser.add_argument('--cpu-seconds', type=float, default=10)
    parser.add_argument('--official-source', required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', args.run_id):
        parser.error('invalid run ID')
    try:
        first, last = map(int, args.puzzles.split(':'))
        cfg = configuration(range(first, last+1), args.seed, args.max_steps)
    except ValueError as e:
        parser.error(str(e))
    metric = load_official(args.official_source)
    repo = ROOT.parents[1]
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all', '--',
                                     'projects/squares-in-squares'], cwd=repo, text=True)
    if dirty:
        raise ValueError('commit project changes before recording a reproducible experiment')
    source_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    cfg['source_sha'] = source_sha
    # Bind source SHA alongside algorithm/code hashes in the run's private config.
    work = ROOT / 'private' / args.run_id
    work.mkdir(parents=True, exist_ok=True)
    config_path = work / 'run.config.json'
    if config_path.exists() and json.loads(config_path.read_text()) != cfg:
        raise ValueError('run ID already has a different configuration')
    atomic_json(config_path, cfg)
    search_cfg = {k: v for k, v in cfg.items() if k != 'source_sha'}
    start = time.perf_counter()
    state, puzzles = optimize(search_cfg, work / 'checkpoint.json', cpu_seconds=args.cpu_seconds,
                              steps_per_call=args.steps_per_call)
    text = serialize(puzzles)
    restored = deserialize(text)
    if restored != puzzles:
        raise ValueError('serialization changed placements')
    sides = {n: validate(n, rows) for n, rows in restored.items()}
    total, results = evaluate(metric, text, cfg['puzzles'])
    if any(reason != 'ok' for _, _, _, reason in results):
        raise ValueError('official metric rejected a locally certified packing')
    # No submission file is emitted; only a checksum of the in-memory CSV.
    artifact_hash = hashlib.sha256(text.encode()).hexdigest()
    experiment = 'squares-in-squares/' + args.run_id
    deps = {p: importlib.metadata.version(p) for p in ['mpmath', 'pandas', 'numpy', 'python-dateutil', 'pytz', 'tzdata', 'six']}
    env = dict(python=platform.python_version(), implementation=platform.python_implementation(),
               system=platform.system(), machine=platform.machine(), dependencies=deps)
    report = dict(schema_version=1, project_id='squares-in-squares', experiment_id=experiment,
                  status='completed' if state['step'] == cfg['max_steps'] else 'planned',
                  source_sha=source_sha,
                  config_path=f'projects/squares-in-squares/experiments/{args.run_id}.config.json',
                  config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(), seed=args.seed,
                  inputs=[dict(logical_id='squares-in-squares/synthetic-puzzle-set', version='unit-squares-v1',
                               sha256=digest(cfg['puzzles']), license='synthetic-generated',
                               provenance='Integers only; generated locally, no competition data.')],
                  environment=dict(platform='codex-cloud', image=json.dumps(env, sort_keys=True),
                                   dependency_lock_sha256=hashlib.sha256((ROOT/'requirements.lock').read_bytes()).hexdigest()),
                  notebook=dict(logical_id='squares-in-squares/offline-runner', version=cfg['code_sha256']),
                  metric_version=f"official-notebook-v{LOCK['notebook_version']}:sha256:{LOCK['source_sha256']}",
                  runtime_seconds=time.perf_counter()-start,
                  checks=[dict(name='serialized-geometry-and-official-metric', method='ran', outcome='passed',
                               detail=json.dumps(dict(completed_steps=state['step'], accepted=state['accepted'],
                                                      cumulative_search_cpu_seconds=state['cpu_seconds'],
                                                      invocation_cpu_budget=args.cpu_seconds,
                                                      steps_per_call=args.steps_per_call,
                                                      local_side_upper_bounds={n: str(v) for n,v in sides.items()},
                                                      official_reasons={n: r for n,_,_,r in results}), sort_keys=True))],
                  results=[dict(name='total', value=total)]+[dict(name=f'n={n}', value=v) for n,v,_,_ in results],
                  artifacts=[dict(logical_id=experiment+'/serialized-packing', sha256=artifact_hash, visibility='private-cloud'),
                             dict(logical_id=experiment+'/checkpoint', sha256=hashlib.sha256((work/'checkpoint.json').read_bytes()).hexdigest(), visibility='private-cloud')])
    atomic_json(work/'manifest.json', report)
    print(json.dumps(dict(experiment_id=experiment, completed_steps=state['step'], total=total)))


if __name__ == '__main__':
    main()
