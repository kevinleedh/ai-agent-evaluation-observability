#!/bin/zsh
set -euo pipefail
CITATION_STUDY_DIR="${0:A:h}"
exec "$CITATION_STUDY_DIR/.venv/bin/python" "$CITATION_STUDY_DIR/citation_experiment.py" "$@"
