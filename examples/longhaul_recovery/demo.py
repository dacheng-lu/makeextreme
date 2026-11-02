#!/usr/bin/env python3
"""Local crash/recovery demonstration with optional Longhaul evidence bookkeeping."""
import argparse
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
EXPECTED = 'Source: alpha\nResult: ready\n'


def call(*args, expected=0):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=30)
    if result.returncode != expected:
        raise RuntimeError(f'{args!r}: exit {result.returncode}, expected {expected}\n{result.stdout}\n{result.stderr}')
    return result.stdout


def run_example(task, checkpoint):
    # These are generated only inside an exclusive temporary directory.
    (task / 'prepare.py').write_text("from pathlib import Path\nPath('input.txt').write_text('alpha\\n')\n")
    (task / 'build.py').write_text(
        "from pathlib import Path\nimport time\np=Path('started')\n"
        "if not p.exists():\n p.write_text('started')\n time.sleep(60)\n"
        "Path('middle.txt').write_text(Path('input.txt').read_text())\n")
    (task / 'report.py').write_text(
        "from pathlib import Path\nPath('report.txt').write_text('Source: '+Path('middle.txt').read_text()+'Result: ready\\n')\n")
    py = shlex.quote(sys.executable)
    stages = [
        {'id': 'prepare', 'run': f'{py} prepare.py', 'check': 'test -s input.txt', 'outputs': ['input.txt']},
        {'id': 'build', 'run': f'{py} build.py', 'check': 'test -s middle.txt',
         'deps': ['input.txt'], 'outputs': ['middle.txt']},
        {'id': 'report', 'run': f'{py} report.py', 'check': 'test -s report.txt',
         'deps': ['middle.txt'], 'outputs': ['report.txt']},
    ]
    (task / 'stages.json').write_text(json.dumps(stages))
    log = (task / 'runner.log').open('w+')
    runner = subprocess.Popen([sys.executable, '-m', 'makeextreme', 'run', str(task)], cwd=ROOT,
                              stdout=log, stderr=log, text=True)
    original_group = None
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if runner.poll() is not None:
                log.flush()
                log.seek(0)
                raise RuntimeError(f'runner exited before interruption: {runner.returncode}\n{log.read()}')
            if (task / 'started').exists() and (task / 'task.json').exists():
                state = json.loads((task / 'task.json').read_text())
                if state.get('stages', {}).get('build', {}).get('pgid'):
                    original_group = (state['stages']['build']['pgid'], state['stages']['build']['pg_start'])
                    break
            time.sleep(0.02)
        else:
            raise RuntimeError('build stage did not reach the interruption point')
        # Only the child runner that this example started is signalled.
        runner.send_signal(signal.SIGKILL)
        runner.wait(timeout=10)
        if runner.returncode != -signal.SIGKILL:
            raise RuntimeError('runner did not stop by SIGKILL')
        call(sys.executable, '-m', 'makeextreme', 'run', str(task))
    finally:
        if runner.poll() is None:
            runner.terminate()
            runner.wait(timeout=10)
        # On a failed recovery, avoid leaving our demo's known process group.
        # Check its start tick to avoid signalling a recycled process ID.
        if original_group:
            from makeextreme import core
            pgid, started = original_group
            if pgid != os.getpgrp() and started and core.starttime(pgid) == started:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        log.close()
    events = [json.loads(line) for line in (task / 'journal.jsonl').read_text().splitlines()]
    starts = {name: sum(e.get('ev') == 'start' and e.get('stage') == name for e in events)
              for name in ('prepare', 'build', 'report')}
    if starts != {'prepare': 1, 'build': 2, 'report': 1}:
        raise RuntimeError(f'unexpected stage starts: {starts}')
    if not any(e.get('ev') == 'recovered_from_crash' and e.get('stage') == 'build' for e in events):
        raise RuntimeError('recovery was not recorded')
    report = task / 'report.txt'
    if report.read_text() != EXPECTED:
        raise RuntimeError('report content did not match the expected result')
    print(f'Runner killed; recovery succeeded. Stage starts: {starts}')

    # This is explicit manual integration: the example verifies the report and
    # writes an observation; it is not a signed receipt or automatic adapter.
    statefile = task / 'longhaul.json'
    def lh(*args, expected=0):
        return call(sys.executable, str(checkpoint), *map(str, args), expected=expected)
    lh('init', statefile, '--task-id', 'report-demo', '--goal', 'Verify the local report')
    lh('artifact', statefile, '--id', 'A1', '--locator', 'report.txt')
    lh('evidence', statefile, '--id', 'E1', '--artifact', 'A1', '--result', 'pass')
    state = json.loads(statefile.read_text())
    state['acceptance'] = [{'id': 'C1', 'criterion': 'Report has the expected content',
                            'status': 'verified', 'evidence_ids': ['E1']}]
    statefile.write_text(json.dumps(state))
    lh('gate', statefile)
    report.write_text(EXPECTED + 'Updated\n')
    lh('artifact', statefile, '--id', 'A1', '--locator', 'report.txt')
    rejected = json.loads(lh('gate', statefile, expected=1))
    if not any('stale' in msg for msg in rejected.get('errors', [])):
        raise RuntimeError(f'gate did not report stale evidence: {rejected}')
    if report.read_text() != EXPECTED + 'Updated\n':
        raise RuntimeError('updated report check failed')
    lh('evidence', statefile, '--id', 'E1', '--artifact', 'A1', '--result', 'pass')
    lh('gate', statefile)
    print('Longhaul gate passed, rejected stale evidence, then passed after a new content check.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--longhaul', required=True, type=Path, help='path to a Longhaul checkout')
    args = parser.parse_args()
    checkpoint = (args.longhaul / 'scripts/checkpoint.py').resolve()
    if not checkpoint.is_file():
        parser.error('Longhaul checkpoint helper not found')
    if not sys.platform.startswith('linux'):
        parser.error('this example needs Linux')
    try:
        if os.readlink('/proc/self') != str(os.getpid()):
            parser.error('/proc must use the current PID namespace')
    except OSError:
        parser.error('cannot inspect /proc/self')
    with tempfile.TemporaryDirectory(prefix='mx-lh-demo-') as d:
        run_example(Path(d), checkpoint)


if __name__ == '__main__':
    main()
