#!/bin/zsh
set -euo pipefail
DRIVE_EXPERIMENT_DIR="${0:A:h}"
exec "$DRIVE_EXPERIMENT_DIR/.venv/bin/python" "$DRIVE_EXPERIMENT_DIR/drive_experiment.py" "$@"
