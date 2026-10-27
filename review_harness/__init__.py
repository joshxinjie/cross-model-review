"""Cross-model review harness: a model from a different family reviews pull requests and whole projects, and the
model that built the work answers the findings.

The harness is shared; each project keeps its own settings in `review/config.yaml`, its reviewer instructions
(REVIEW.md by default), its author instructions and its decision log. The harness reads those from the project's
trusted checkout (main), named by REVIEW_PROJECT_ROOT (default: the current directory).

Run as: PYTHONPATH=<this repo> python -m review_harness.run --help
"""
