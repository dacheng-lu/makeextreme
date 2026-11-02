#!/bin/sh
# One cron tick for a makeextreme task. A tick only STARTS the worker and REPORTS; it decides nothing.
#
#   a live runner holds the lock -> the runner exits 3 and this tick does nothing (reported as "busy")
#   a finished task              -> nothing to do
#   a crashed or killed task     -> continues from the last green stage
#
# usage:  cron_tick.sh <task_dir>
# crontab: */10 * * * * /path/to/makeextreme/examples/cron_tick.sh /path/to/task >> /path/to/tick.log 2>&1
#
# Exit code: 0 complete / busy / waiting for approval; 2 a stage failed (the next tick retries it);
# 5 an uncertain stage needs a human; 7 a stage waits for a human's answer; 69 no usable python interpreter (nothing ran); anything else = refused (invalid spec,
# secret-shaped value in the record).
# makeextreme ships no watchdog or restart daemon on purpose: cron is the restarter.
set -u
task=$(cd -- "${1:?usage: cron_tick.sh <task_dir>}" 2>/dev/null && pwd) || { echo "makeextreme: no such task directory" >&2; exit 64; }
self=$(readlink -f -- "$0" 2>/dev/null || printf %s "$0")  # started through a symlink: the repository is where the script really is
cd "$(dirname "$self")/.." || exit 64
repo=$(pwd)
py=${PYTHON:-python3}
case $py in */*) [ -x "$py" ] && usable=y || usable= ;; *) command -v "$py" >/dev/null 2>&1 && usable=y || usable= ;; esac
[ -n "$usable" ] || { echo "makeextreme: no usable python interpreter: $py" >&2; exit 69; }
q() { printf "'%s'" "$(printf %s "$1" | sed "s/'/'\\\\''/g")"; }  # single-quote for a shell, whatever the path contains
"$py" -m makeextreme run "$task"
rc=$?
case $rc in
  0) echo "makeextreme: complete" ;;
  3) echo "makeextreme: busy (another runner holds the lock)"; rc=0 ;;
  4) echo "makeextreme: waiting for approval: cd $(q "$repo") && $(q "$py") -m makeextreme approve $(q "$task") <stage>"; rc=0 ;;
  5) echo "makeextreme: an UNCERTAIN stage needs a human: cd $(q "$repo") && $(q "$py") -m makeextreme resolve $(q "$task") <stage> --done | --retry" ;;
  7) echo "makeextreme: waiting for an answer (question.json in the task directory): write it where the stage reads it, delete $(q "$task")/question.json, then the next tick continues" ;;
  2) echo "makeextreme: a stage failed; the next tick retries it" ;;
  *) echo "makeextreme: refused (rc=$rc), see the message above" ;;
esac
exit $rc
