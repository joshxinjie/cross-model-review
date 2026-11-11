"""Synthetic fixtures only; no network, accounts, competition data or submissions."""
import hashlib
import json
import math
import os
import subprocess
import sys
import types

import pytest

pytest.importorskip('mpmath', reason='install projects/squares-in-squares/requirements.lock for solver tests')

from sis.geometry import validate
from sis.metric import LOCK, ROOT, evaluate, load_official
from sis.optimize import atomic_json, configuration, digest, optimize, read_checkpoint
from sis.packing import Square, deserialize, grid, literal, serialize


def test_every_grid_and_serialized_geometry():
    total = 0.0
    rows = 0
    for n in range(1, 1001):
        original = grid(n)
        assert grid(n) == original
        text = serialize({n: original})
        restored = deserialize(text)
        assert restored == {n: original}
        side = math.isqrt(n-1)+1
        assert validate(n, restored[n], ('0', '0', str(side))) == side
        total += side/math.sqrt(n)-1
        rows += len(original)
    assert rows == 500500
    assert total == pytest.approx(28.93766991655058, abs=1e-12)


@pytest.mark.parametrize('n', [0, 1001, -1, True, 1.5])
def test_grid_range(n):
    with pytest.raises(ValueError):
        grid(n)


@pytest.mark.parametrize('text', ['nan', 'NaN', 'Infinity', '1/2', 'sqrt(2)', '', ' 1',
                                  '1\n', '1_000', '1e400', '1e-1001', '1e999999999999999999999999999999999999999', '9'*101, '10001'])
def test_bad_literals(text):
    with pytest.raises(ValueError):
        literal(text)


def test_decimal_and_angle_roundtrip():
    s = Square('0.123456789012345678901234567890123456789', '-.25', '1.5e-30')
    assert deserialize(serialize({1: (s,)}))[1][0] == s
    assert literal('1.5e-3') == literal('.0015')
    # This sub-double difference really overlaps, without epsilon forgiveness.
    with pytest.raises(ValueError, match='overlap'):
        validate(2, [Square('.5','.5'), Square('1.4999999999999999999999999999999999','.5')])


@pytest.mark.parametrize('mutate', [
    lambda t: t.replace('id,n,square_id,x,y,angle', 'id,n,square_id,x,y,angle,L'),
    lambda t: t.replace('1,2,1', '0,2,1'),
    lambda t: t.replace('1,2,1', '1,2,0'),
    lambda t: t.replace('1,2,1', '1,2,2'),
    lambda t: t.replace('1,2,1', '1,1001,1'),
    lambda t: '\n'.join(t.splitlines()[:-1])+'\n',
    lambda t: t.replace('0,2,0', '-1,2,0'),
    lambda t: t.replace('0.5,0.5,0', '0.5,0.5,0,unexpected'),
    lambda t: t.replace('0.5,0.5,0', '0.5,0.5'),
])
def test_bad_csv(mutate):
    with pytest.raises(ValueError):
        deserialize(mutate(serialize({2: grid(2)})))


def test_overlap_contact_translation_boundary():
    assert validate(2, [Square('0','0'),Square('1','0')]) == 2  # edge contact
    assert validate(2, [Square('0','0'),Square('1','1')]) == 2  # corner contact
    assert validate(2, [Square('-7','10'),Square('-6','10')]) == 2
    with pytest.raises(ValueError, match='overlap'):
        validate(2, [Square('0','0'),Square('.9','.9')])
    with pytest.raises(ValueError, match='outside'):
        validate(1, grid(1), ('0','0','.9999999999999999999999999999'))
    with pytest.raises(ValueError):
        validate(2, grid(1))


def test_rotations_radians_and_interval_failure_closed():
    side = validate(1, [Square('0','0','0.7853981633974483')], ('-1','-1','2'))
    assert 1.414 < float(side) < 1.415
    assert validate(2, [Square('0','0','.7'),Square('2','0','-.7')]) > 3
    with pytest.raises(ValueError):
        validate(2, [Square('0','0','.7'),Square('.1','.1','-.7')])
    with pytest.raises(ValueError):
        validate(1, [Square('0','0','.7')], ('-.5','-.5','1'))


def test_checkpoint_split_equals_uninterrupted(tmp_path):
    cfg = configuration([1,2,5], seed=42, max_steps=12)
    full, full_puzzles = optimize(cfg, tmp_path/'full.json', cpu_seconds=30)
    first, _ = optimize(cfg, tmp_path/'split.json', cpu_seconds=30, steps_per_call=5)
    assert first['step'] == 5
    split, split_puzzles = optimize(cfg, tmp_path/'split.json', cpu_seconds=30)
    assert split['step'] == full['step'] == 12
    assert split_puzzles == full_puzzles
    assert split['accepted'] == full['accepted']
    for n, squares in split_puzzles.items():
        assert validate(n, deserialize(serialize({n:squares}))[n]) <= math.isqrt(n-1)+1
    done, _ = optimize(cfg, tmp_path/'split.json', cpu_seconds=30)
    assert done['step'] == 12
    with pytest.raises(ValueError, match='configuration'):
        read_checkpoint(tmp_path/'split.json', configuration([1,2,5], seed=43, max_steps=12))


def test_checkpoint_corruption_and_geometry_rechecked(tmp_path):
    cfg = configuration([2], max_steps=0)
    p = tmp_path/'check.json'
    optimize(cfg,p,cpu_seconds=0)
    env = json.loads(p.read_text())
    env['state']['step'] = 1
    atomic_json(p,env)
    with pytest.raises(ValueError, match='checksum'):
        read_checkpoint(p,cfg)
    env['state']['step'] = 0
    env['state']['puzzles']['2'][1]['x'] = '0.5'
    env['sha256'] = digest(env['state'])
    atomic_json(p,env)
    with pytest.raises(ValueError, match='overlap'):
        read_checkpoint(p,cfg)


@pytest.mark.parametrize('budget', [-1, float('nan'), float('inf'), 3601])
def test_bad_cpu_budget(tmp_path,budget):
    with pytest.raises(ValueError):
        optimize(configuration([1]),tmp_path/'x',cpu_seconds=budget)


def test_zero_budget_saves_valid_grid(tmp_path):
    state, puzzles = optimize(configuration([1,1000]),tmp_path/'x',cpu_seconds=0)
    assert state['step'] == 0
    assert puzzles[1000] == grid(1000)


def test_adapter_rejects_unpinned_code_before_execution(tmp_path):
    p = tmp_path/'metric.py'
    p.write_text('raise RuntimeError("must not execute")')
    with pytest.raises(ValueError, match='hash mismatch'):
        load_official(p)


def test_adapter_dispatch_with_synthetic_metric():
    calls = []
    def single(n, rows):
        calls.append(n)
        return n, .25, 'synthetic', 'ok'
    module = types.SimpleNamespace(_parse_submission_csv=lambda text:{2:[],5:[]},
                                   evaluate_single_puzzle=single, infeasible_score=lambda n:.5)
    total, results = evaluate(module,'synthetic',[1,2])
    assert total == .75 and calls == [2]
    assert results[0] == (1,.5,None,'missing from submission')


@pytest.fixture
def official():
    source = os.environ.get('SIS_OFFICIAL_SOURCE')
    if not source:
        pytest.skip('set SIS_OFFICIAL_SOURCE to hash-pinned public notebook export for integration')
    return load_official(source)


def test_official_parity_valid_invalid_missing_and_no_side_effects(official, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    puzzles = {n:grid(n) for n in [1,2,4,5,32]}
    total, results = evaluate(official,serialize(puzzles),[1,2,3,4,5,32])
    expected = sum((math.isqrt(n-1)+1)/math.sqrt(n)-1 for n in [1,2,3,4,5,32])
    assert total == pytest.approx(expected)
    assert [r[3] for r in results] == ['ok','ok','missing from submission','ok','ok','ok']
    for text in [serialize({2:[Square('.5','.5'),Square('.6','.5')]}),
                 serialize({2:grid(2)}).replace('1,2,1','1,2,0'),
                 serialize({2:grid(2)}).replace('0.5,0.5,0','sqrt(2),0.5,0')]:
        value, rows = evaluate(official,text,[2])
        assert value == official.infeasible_score(2)
        assert rows[0][2] is None and rows[0][3] != 'ok'
    assert list(tmp_path.iterdir()) == []


def test_official_entrypoint_parity(official, tmp_path, monkeypatch):
    import pandas as pd
    from io import StringIO
    monkeypatch.chdir(tmp_path)
    text = serialize({n:grid(n) for n in [1,2,4,5]})
    expected, results = evaluate(official,text,[1,2,3,4,5])
    # Public score entry point writes details; isolate them to a temporary cwd.
    sub = pd.read_csv(StringIO(text),dtype=str)
    solution = pd.DataFrame({'id':range(5),'n':[1,2,3,4,5]})
    assert official.score(solution,sub,'id') == expected
    assert (tmp_path/'submission_details.csv').exists()


def test_cpu_deadline_does_not_commit_unfinished_proposal(tmp_path, monkeypatch):
    import time
    import sis.optimize as search
    real = search.validate
    def slow(n, squares):
        # Baseline and resumed validation stay outside the timer.
        if any(s.angle != '0' for s in squares):
            while True:
                pass
        return real(n, squares)
    monkeypatch.setattr(search, 'validate', slow)
    start = time.process_time()
    state, puzzles = optimize(configuration([1],max_steps=2),tmp_path/'x',cpu_seconds=.05)
    assert time.process_time()-start < 1.0
    assert state['step'] == 0 and puzzles[1] == grid(1)
    assert read_checkpoint(tmp_path/'x',state['config'])['step'] == 0


def test_extract_synthetic_version_and_hash_checks(tmp_path, monkeypatch):
    from sis.extract_metric import extract
    import sis.extract_metric as extractor
    source = 'SYNTHETIC = True\n'
    payload = dict(metadata=dict(id=123,currentVersionNumber=7),
                   blob=dict(sourceNullable=json.dumps(dict(cells=[dict(cell_type='code',source=[source.rstrip('\n')])]))))
    p = tmp_path/'download.json'
    p.write_text(json.dumps(payload))
    monkeypatch.setattr(extractor,'LOCK',dict(kernel_id=123,notebook_version=7,
                                            source_sha256=hashlib.sha256(source.encode()).hexdigest()))
    assert extract(p) == source
    payload['metadata']['currentVersionNumber'] = 8
    p.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='version'):
        extract(p)


def test_runner_manifest_schema_reproducibility_and_private_outputs(official, tmp_path):
    import shutil
    from review_harness.validate import schema_errors
    repo = tmp_path/'repo'
    project = repo/'projects'/'squares-in-squares'
    project.mkdir(parents=True)
    shutil.copytree(ROOT/'sis',project/'sis',ignore=shutil.ignore_patterns('__pycache__'))
    for name in ['requirements.lock','metric.lock.json']:
        shutil.copy(ROOT/name,project/name)
    (repo/'.gitignore').write_text('__pycache__/\nprojects/*/private/\n')
    subprocess.run(['git','init','-q',str(repo)],check=True)
    subprocess.run(['git','add','.'],cwd=repo,check=True)
    subprocess.run(['git','-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid',
                    'commit','-qm','Synthetic test source'],cwd=repo,check=True)
    env = dict(os.environ,PYTHONPATH=str(project))
    cmd = [sys.executable,'-m','sis','--run-id','synthetic-run','--puzzles','1:5','--max-steps','4',
           '--steps-per-call','2','--cpu-seconds','30','--official-source',os.environ['SIS_OFFICIAL_SOURCE']]
    for _ in range(2):
        subprocess.run(cmd,cwd=repo,env=env,check=True,capture_output=True,text=True)
    private = project/'private'/'synthetic-run'
    manifest = json.loads((private/'manifest.json').read_text())
    schema = json.loads((ROOT.parent/'experiment.schema.json').read_text())
    assert schema_errors(manifest,schema) == []
    assert manifest['status'] == 'completed'
    assert manifest['config_sha256'] == hashlib.sha256((private/'run.config.json').read_bytes()).hexdigest()
    check = json.loads(manifest['checks'][0]['detail'])
    assert check['completed_steps'] == 4
    assert manifest['metric_version'].endswith(LOCK['source_sha256'])
    assert 'source_sha' in json.loads((private/'run.config.json').read_text())
    assert not list(repo.rglob('*.csv'))
    assert subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True) == ''
    # A different declared seed cannot resume an existing run ID.
    failed = subprocess.run(cmd+['--seed','3'],cwd=repo,env=env,capture_output=True,text=True)
    assert failed.returncode != 0 and 'different configuration' in failed.stderr
    # Modified source cannot claim a clean reproducible run.
    with (project/'sis'/'__init__.py').open('a') as out:
        out.write('\n# modified synthetic code\n')
    failed = subprocess.run(cmd,cwd=repo,env=env,capture_output=True,text=True)
    assert failed.returncode != 0 and 'commit project changes' in failed.stderr
