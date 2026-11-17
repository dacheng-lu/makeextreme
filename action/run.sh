#!/usr/bin/env bash
# Keep input out of shell source and preserve the action's own module resolution.
set -euo pipefail
if [[ -z "${MAKEEXTREME_TASK_DIR:-}" ]]; then
  echo 'makeextreme: task-dir is required' >&2
  exit 64
fi
case "$MAKEEXTREME_TASK_DIR" in
  /*) task_dir=$MAKEEXTREME_TASK_DIR ;;
  *) task_dir="${GITHUB_WORKSPACE:?GITHUB_WORKSPACE is required}/$MAKEEXTREME_TASK_DIR" ;;
esac
cd -- "${MAKEEXTREME_ACTION_PATH:?MAKEEXTREME_ACTION_PATH is required}"
exec python3 -m makeextreme run "$task_dir"
