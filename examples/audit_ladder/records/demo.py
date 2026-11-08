#!/usr/bin/env python3
"""Offline fixture: kill report stage, resume, reject drift, check Longhaul handoff."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from new_task import create

ROOT = Path(__file__).resolve().parents[3]


def run(args, expected=0):
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=30)
    if p.returncode != expected:
        raise RuntimeError(f'exit {p.returncode}, expected {expected}: {p.stdout} {p.stderr}')
    return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--longhaul', required=True, type=Path)
    args = parser.parse_args()
    helper = args.longhaul.resolve() / 'scripts/check_audit_handoff.py'
    with tempfile.TemporaryDirectory(prefix='audit-record-demo-') as tmp:
        root = Path(tmp)
        bundle = root / 'bundle'
        (bundle / 'evidence').mkdir(parents=True)
        evidence = bundle / 'evidence/fixture.txt'
        evidence.write_text('Synthetic boundary check: no real target executed.\n')
        scope = {'base': 'a' * 40, 'head': 'b' * 40}
        ref = {'path': 'evidence/fixture.txt', 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}
        records = {'version': 1, 'scope': scope, 'coverage': [{'id': 'fixture', 'status': 'checked', 'evidence': [ref]}], 'findings': []}
        (bundle / 'scope.json').write_text(json.dumps(scope))
        (bundle / 'records.json').write_text(json.dumps(records))
        task = root / 'task'
        create(bundle, task)
        # Controlled fixture pause, not target-supplied code.
        (task / 'pause.py').write_text("from pathlib import Path\nimport time\np=Path('paused')\nif not p.exists():\n p.write_text('yes')\n time.sleep(30)\n")
        stages = json.loads((task / 'stages.json').read_text())
        import shlex
        stages[1]['run'] = shlex.quote(sys.executable) + ' pause.py && ' + stages[1]['run']
        stages[1]['deps'].append('pause.py')
        (task / 'stages.json').write_text(json.dumps(stages))
        command = [sys.executable, '-m', 'makeextreme', 'run', str(task)]
        with (root / 'log').open('w') as log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log)
            group = None
            try:
                deadline = time.monotonic() + 10
                while not (task / 'paused').exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('fixture failed to reach pause')
                    time.sleep(0.02)
                stage = json.loads((task / 'task.json').read_text())['stages']['report']
                group = (stage['pgid'], stage['pg_start'])
                process.kill()
                process.wait(timeout=5)
                run(command)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                if group:
                    sys.path.insert(0, str(ROOT))
                    from makeextreme import core
                    if core.starttime(group[0]) == group[1]:
                        try:
                            os.killpg(group[0], signal.SIGKILL)
                        except ProcessLookupError:
                            pass
        events = [json.loads(line) for line in (task / 'journal.jsonl').read_text().splitlines()]
        starts = {s: sum(e.get('ev') == 'start' and e.get('stage') == s for e in events) for s in ('validate', 'report')}
        if starts != {'validate': 1, 'report': 2}:
            raise RuntimeError(f'bad recovery counts {starts}')
        handoff = {'version': 1, 'head': scope['head'], 'artifacts': {n: hashlib.sha256((task / n).read_bytes()).hexdigest() for n in ('validated.json', 'report.md')}, 'unresolved': [], 'open_coverage': [], 'limitations': ['Synthetic fixture only; no real audit or authenticated reviewer.']}
        (task / 'handoff.json').write_text(json.dumps(handoff))
        check = [sys.executable, str(helper), str(task), '--head', scope['head']]
        run(check)
        (task / 'report.md').write_text('changed')
        run(check, expected=1)
        run(command)
        run(check)
        scope['head'] = 'c' * 40
        (task / 'scope.json').write_text(json.dumps(scope))
        run(command, expected=2)
        print(json.dumps({'fixture': True, 'stage_starts': starts, 'handoff': 'pass', 'artifact_drift': 'rejected then repaired', 'source_drift': 'rejected'}))


if __name__ == '__main__':
    main()
