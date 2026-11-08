#!/usr/bin/env python3
"""Create a fresh task from a trusted local bundle (scope.json, records.json, evidence/)."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import sys


def create(source, target):
    # Caller supplies a reviewed bundle. No commands are taken from its records.
    target.mkdir(parents=True, exist_ok=False)
    for name in ('scope.json', 'records.json'):
        shutil.copyfile(source / name, target / name)
    shutil.copytree(source / 'evidence', target / 'evidence')
    shutil.copyfile(Path(__file__).with_name('audit_records.py'), target / 'audit_records.py')
    command = shlex.quote(sys.executable) + ' audit_records.py '
    deps = ['scope.json', 'evidence', 'audit_records.py']
    stages = [
        {'id': 'validate', 'run': command + 'snapshot', 'check': command + 'check-snapshot',
         'deps': deps + ['records.json'], 'outputs': ['validated.json']},
        {'id': 'report', 'run': command + 'report', 'check': command + 'check-report',
         'deps': deps + ['validated.json'], 'outputs': ['report.md']},
    ]
    (target / 'stages.json').write_text(json.dumps(stages, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('bundle', type=Path)
    p.add_argument('task', type=Path)
    a = p.parse_args()
    create(a.bundle, a.task)
