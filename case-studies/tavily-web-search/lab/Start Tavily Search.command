#!/bin/zsh
set -u
cd -- "${0:A:h}" || exit 1
task_python="${PWD}/.venv/bin/python"
if [[ ! -x "$task_python" ]]; then
  print 'Create .venv and install requirements.txt as described in README.md.'
  exit 1
fi
"$task_python" terminal_tavily.py "$@"
task_status=$?
if [[ -t 0 ]]; then
  print "\nExit status: $task_status"
  read 'task_exit?Press Enter to close.'
fi
exit "$task_status"
