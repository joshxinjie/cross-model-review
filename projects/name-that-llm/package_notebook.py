"""Build a standalone offline Kaggle notebook; never upload or submit it."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build_notebook(source_sha):
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha) or source_sha == "0" * 40:
        raise ValueError("Supply the committed source SHA")
    files = {name: (ROOT / name).read_text() for name in ("baseline.py", "baseline.json", "requirements.txt", "LICENSE")}
    bundle_hash = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    setup = '''from pathlib import Path
import json, os, subprocess, sys
# Set these provenance values before running; no credentials belong here.
INPUT_VERSION = "REPLACE_WITH_IMMUTABLE_INPUT_VERSION"
IMAGE = "REPLACE_WITH_KAGGLE_IMAGE_VERSION"
RUN_ID = "baseline-001"
# Attach a private wheelhouse dataset if the pinned packages are not preinstalled.
WHEELHOUSE = None  # e.g. Path('/kaggle/input/datasets/OWNER/baseline-wheels')
INPUT = Path('/kaggle/input/competitions/name-that-llm')
OUTPUT = Path('/kaggle/working')
assert not INPUT_VERSION.startswith('REPLACE_') and not IMAGE.startswith('REPLACE_'), 'Fill provenance first'
'''
    execute = f'''FILES = {files!r}
SOURCE_SHA = {source_sha!r}
BUNDLE_SHA256 = {bundle_hash!r}
staging = OUTPUT / '.baseline-source'
staging.mkdir(exist_ok=True)
for name, content in FILES.items():
    (staging / name).write_text(content)
env = os.environ.copy()
if WHEELHOUSE is not None:
    dependencies = OUTPUT / '.baseline-deps'
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--find-links', str(WHEELHOUSE),
                    '--target', str(dependencies), '-r', str(staging / 'requirements.txt')], check=True)
    env['PYTHONPATH'] = str(dependencies)
# A fresh interpreter avoids mixing notebook-preloaded packages with wheelhouse versions.
check = "import importlib.metadata as m; " + "; ".join(
    f"assert m.version({{line.split('==')[0]!r}}) == {{line.split('==')[1]!r}}, 'Attach pinned offline wheels'"
    for line in FILES['requirements.txt'].splitlines() if '==' in line)
subprocess.run([sys.executable, '-c', check], env=env, check=True)
metadata = dict(run_id=RUN_ID, source_sha=SOURCE_SHA, input_version=INPUT_VERSION,
                image=IMAGE, platform='kaggle', license='CC BY-SA 4.0; competition rules apply',
                provenance='Official Kaggle Name That LLM competition input', notebook_version=BUNDLE_SHA256)
(staging / 'metadata.json').write_text(json.dumps(metadata))
subprocess.run([sys.executable, str(staging / 'baseline.py'), '--train', str(INPUT / 'train.csv'),
                '--test', str(INPUT / 'test.csv'), '--output', str(OUTPUT / RUN_ID),
                '--metadata', str(staging / 'metadata.json')], env=env, check=True)
# Kaggle expects this filename at the working-directory root.
import shutil
shutil.copyfile(OUTPUT / RUN_ID / 'submission.parquet', OUTPUT / 'submission.parquet')
'''
    def cell(kind, text):
        result = {"cell_type": kind, "metadata": {}, "source": text.splitlines(keepends=True)}
        if kind == "code":
            result.update(execution_count=None, outputs=[])
        return result
    return {"nbformat": 4, "nbformat_minor": 4,
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                         "language_info": {"name": "python", "version": "3.12"},
                         "name_that_llm": {"internet": False, "accelerator": "none", "source_sha": source_sha,
                                           "bundle_sha256": bundle_hash}},
            "cells": [cell("markdown", "# Name That LLM CPU baseline\nSet Kaggle Internet **off** and accelerator **None**. "
                           "Attach competition input and optional offline wheels. Review current rules and accept personally. "
                           "This notebook does not submit. Source code only; keep all outputs private.\n"),
                      cell("code", setup), cell("code", execute)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # A notebook must not claim a commit that does not contain its source bundle.
    for name in ("baseline.py", "baseline.json", "requirements.txt", "package_notebook.py", "LICENSE"):
        committed = subprocess.run(["git", "show", f"{args.source_sha}:projects/name-that-llm/{name}"],
                                   cwd=ROOT, check=True, capture_output=True).stdout
        if committed != (ROOT / name).read_bytes():
            raise ValueError("Commit source changes before packaging")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(build_notebook(args.source_sha), handle, indent=2)


if __name__ == "__main__":
    main()
