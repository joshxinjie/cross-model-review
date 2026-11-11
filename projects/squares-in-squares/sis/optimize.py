"""Single-process bounded hill climbing with deterministic per-step randomness."""
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import random
import signal
from contextlib import contextmanager
import time

from .geometry import validate
from .packing import Square, grid, puzzle_number

ALGORITHM = 'single-square-hillclimb-v1'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def code_hash():
    root = Path(__file__).parent
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.py'))})


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    try:
        with tmp.open('w') as f:
            json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def configuration(ns, seed=0, max_steps=100):
    ns = list(ns)
    if not ns or ns != sorted(set(ns)):
        raise ValueError('puzzles must be nonempty, unique and sorted')
    for n in ns:
        puzzle_number(n)
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError('seed must be an integer in 0..2**63-1')
    if type(max_steps) is not int or not 0 <= max_steps <= 100000:
        raise ValueError('max_steps must be an integer in 0..100000')
    return dict(algorithm=ALGORITHM, puzzles=ns, seed=seed, max_steps=max_steps,
                code_sha256=code_hash(), precision='lossless-decimal-strings; interval-50-100-200-dps',
                checkpoint='atomic-json-after-each-step; sha256; revalidate-on-resume')


def initial(config):
    return dict(config=config, step=0, accepted=0, cpu_seconds=0.0,
                puzzles={str(n): [asdict(s) for s in grid(n)] for n in config['puzzles']})


def decode(state, config):
    if set(state) != {'config', 'step', 'accepted', 'cpu_seconds', 'puzzles'} or state['config'] != config:
        raise ValueError('checkpoint configuration mismatch')
    if type(state['step']) is not int or not 0 <= state['step'] <= config['max_steps']:
        raise ValueError('invalid checkpoint step')
    if type(state['accepted']) is not int or not 0 <= state['accepted'] <= state['step']:
        raise ValueError('invalid accepted count')
    if not isinstance(state['cpu_seconds'], (int, float)) or not math.isfinite(state['cpu_seconds']) or state['cpu_seconds'] < 0:
        raise ValueError('invalid CPU accounting')
    if set(state['puzzles']) != {str(n) for n in config['puzzles']}:
        raise ValueError('checkpoint puzzle set mismatch')
    puzzles = {int(n): tuple(Square(**s) for s in rows) for n, rows in state['puzzles'].items()}
    for n, squares in puzzles.items():
        if validate(n, squares) > math.isqrt(n-1)+1:
            raise ValueError('checkpoint is worse than grid')
    return puzzles


def read_checkpoint(path, config):
    envelope = json.loads(Path(path).read_text())
    if set(envelope) != {'state', 'sha256'} or digest(envelope['state']) != envelope['sha256']:
        raise ValueError('checkpoint checksum mismatch')
    decode(envelope['state'], config)
    return envelope['state']


def save_checkpoint(path, state):
    atomic_json(path, {'state': state, 'sha256': digest(state)})


class CpuDeadline(Exception):
    """Private control flow for the per-proposal CPU timer."""


@contextmanager
def cpu_deadline(seconds):
    """Linux/POSIX main-thread CPU timer; restore any previous handler/timer."""
    if not hasattr(signal, 'ITIMER_PROF'):
        raise RuntimeError('CPU-bounded search requires POSIX ITIMER_PROF')
    old_handler = signal.getsignal(signal.SIGPROF)
    def expire(signum, frame):
        raise CpuDeadline()
    signal.signal(signal.SIGPROF, expire)
    old_timer = signal.setitimer(signal.ITIMER_PROF, max(seconds, 0.000001))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_PROF, *old_timer)
        signal.signal(signal.SIGPROF, old_handler)


def optimize(config, checkpoint, *, cpu_seconds=10.0, steps_per_call=None):
    """Resume up to max_steps, using at most one CPU budget per invocation.

    A POSIX CPU timer interrupts an unfinished proposal at the deadline. Setup,
    checkpoint validation and atomic I/O are outside the search CPU budget.
    No subprocess, threads, GPU or network.
    Each candidate depends only on seed+global step, so split runs reproduce
    the same placements and acceptance counts at the same completed step.
    """
    if not math.isfinite(cpu_seconds) or not 0 <= cpu_seconds <= 3600:
        raise ValueError('CPU budget must be finite in 0..3600 seconds')
    if steps_per_call is not None and (type(steps_per_call) is not int or steps_per_call < 0):
        raise ValueError('steps_per_call must be a nonnegative integer')
    # Reject hand-built/modified configurations before touching a checkpoint.
    if config != configuration(config['puzzles'], config['seed'], config['max_steps']):
        raise ValueError('unsupported configuration')
    path = Path(checkpoint)
    state = read_checkpoint(path, config) if path.exists() else initial(config)
    puzzles = decode(state, config)
    sides = {n: validate(n, rows) for n, rows in puzzles.items()}
    start, previous_cpu, done = time.process_time(), state['cpu_seconds'], 0
    while state['step'] < config['max_steps'] and time.process_time()-start < cpu_seconds:
        if steps_per_call is not None and done >= steps_per_call:
            break
        rng = random.Random(f"{config['seed']}:{state['step']}")
        n = rng.choice(config['puzzles'])
        rows = list(puzzles[n])
        sid = rng.randrange(n)
        s = rows[sid]
        scale = rng.choice([0.5, 0.1, 0.01, 0.001])
        try:
            with cpu_deadline(cpu_seconds - (time.process_time()-start)):
                # repr keeps candidate values round-trippable as decimal literals.
                rows[sid] = Square(repr(float(s.x)+rng.uniform(-scale, scale)),
                                   repr(float(s.y)+rng.uniform(-scale, scale)),
                                   repr(float(s.angle)+rng.uniform(-scale, scale)))
                side = validate(n, rows)
        except ValueError:
            side = None
        except CpuDeadline:
            break  # Replay this unfinished step on the next invocation.
        if side is not None and side <= sides[n]:
            puzzles[n], sides[n] = tuple(rows), side
            state['puzzles'][str(n)] = [asdict(s) for s in rows]
            state['accepted'] += 1
        state['step'] += 1
        done += 1
        state['cpu_seconds'] = previous_cpu + time.process_time()-start
        save_checkpoint(path, state)
    state['cpu_seconds'] = previous_cpu + time.process_time()-start
    save_checkpoint(path, state)
    return state, puzzles
