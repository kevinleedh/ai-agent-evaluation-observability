#!/bin/zsh
set -euo pipefail
TASK_DIR="${0:A:h}"
exec "$TASK_DIR/.venv/bin/python" "$TASK_DIR/terminal_drive.py" "$@"
