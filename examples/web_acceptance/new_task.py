#!/usr/bin/env python3
"""Create an isolated regression task from a trusted local dev-lu.com snapshot."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('site', type=Path, help='local site snapshot containing index.html')
p.add_argument('task', type=Path, help='new task directory')
p.add_argument('--skip-browser', action='store_true', help='record skipped instead of executing Chromium')
a = p.parse_args()
site_path = a.site.absolute()
if any(path.is_symlink() for path in (site_path, *site_path.parents)):
    p.error('site path must not contain symbolic links')
for root, dirs, files in os.walk(a.site, followlinks=False):
    for name in dirs + files:
        if (Path(root) / name).is_symlink():
            p.error('site snapshot must not contain symbolic links')
if not (a.site / 'index.html').is_file():
    p.error('site must contain index.html')
a.task.mkdir(parents=True, exist_ok=False)
shutil.copytree(a.site, a.task / 'site', ignore=shutil.ignore_patterns('.git'))
shutil.copyfile(Path(__file__).with_name('probe.py'), a.task / 'probe.py')
command = shlex.quote(sys.executable) + ' probe.py '
stages = [{'id': 'browser', 'run': command + ('skip' if a.skip_browser else 'run'),
           'check': command + 'check', 'deps': ['site', 'probe.py'], 'outputs': ['report.json']}]
(a.task / 'stages.json').write_text(json.dumps(stages, indent=2) + '\n')
print(a.task)
