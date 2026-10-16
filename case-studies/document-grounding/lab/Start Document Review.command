#!/bin/zsh
set -u
cd -- "${0:A:h}" || exit 1
task_python="${PWD}/.venv/bin/python"
if [[ ! -x "$task_python" ]]; then
  print 'Create .venv and install requirements.txt as described in README.md.'
  exit 1
fi
"$task_python" terminal_documents.py "$@"
task_status=$?
print "\nExit status: $task_status"
read 'task_exit?Press Enter to close.'
exit "$task_status"
