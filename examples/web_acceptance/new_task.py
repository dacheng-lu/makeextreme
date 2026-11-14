#!/usr/bin/env python3
"""Create an isolated regression task from a trusted local dev-lu.com snapshot."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import os
import sys


class Refused(Exception):
    """The snapshot cannot be copied as it is."""


def copy_snapshot(src: Path, dst: Path) -> None:
    """Copy the regular files and directories of `src` into `dst`, never a symbolic link.

    The link check and the read are the same operation: `O_NOFOLLOW` fails on a link
    that appeared after the entry was listed, so no byte from outside the snapshot can
    reach the task. A `.git` entry is the snapshot's history, not its content.
    """
    dst.mkdir()
    with os.scandir(src) as entries:
        for entry in sorted(entries, key=lambda e: e.name):
            if entry.name == '.git':
                continue
            target = dst / entry.name
            if entry.is_symlink():
                raise Refused(f'site snapshot must not contain symbolic links: {entry.path}')
            if entry.is_dir(follow_symlinks=False):
                copy_snapshot(Path(entry.path), target)
            elif entry.is_file(follow_symlinks=False):
                fd = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, 'rb') as source, open(target, 'xb') as sink:
                    shutil.copyfileobj(source, sink)
            else:
                raise Refused(f'site snapshot must contain only files and directories: {entry.path}')


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('site', type=Path, help='local site snapshot containing index.html')
p.add_argument('task', type=Path, help='new task directory')
p.add_argument('--skip-browser', action='store_true', help='record skipped instead of executing the browser')
a = p.parse_args()
site_path = a.site.absolute()
if any(path.is_symlink() for path in (site_path, *site_path.parents)):
    p.error('site path must not contain symbolic links')
if not (a.site / 'index.html').is_file():
    p.error('site must contain index.html')
a.task.mkdir(parents=True, exist_ok=False)
try:
    copy_snapshot(a.site, a.task / 'site')
except Refused as e:
    shutil.rmtree(a.task, ignore_errors=True)
    p.error(str(e))
except OSError as e:
    shutil.rmtree(a.task, ignore_errors=True)
    p.error(f'cannot copy the snapshot: {e.strerror or e}')
shutil.copyfile(Path(__file__).with_name('probe.py'), a.task / 'probe.py')
command = shlex.quote(sys.executable) + ' probe.py '
stages = [{'id': 'browser', 'run': command + ('skip' if a.skip_browser else 'run'),
           'check': command + 'check', 'deps': ['site', 'probe.py'], 'outputs': ['report.json']}]
(a.task / 'stages.json').write_text(json.dumps(stages, indent=2) + '\n')
print(a.task)
