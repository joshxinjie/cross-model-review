"""Tests run the harness against a small fixture project (tests/fixture), as a project's workflow would."""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
os.environ["REVIEW_PROJECT_ROOT"] = str(REPO / "tests" / "fixture")
sys.path.insert(0, str(REPO))
