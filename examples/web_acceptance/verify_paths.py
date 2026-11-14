#!/usr/bin/env python3
"""Prove, on a real browser, every outcome the release-digest example claims.

This is the optional end-to-end check for `examples/web_acceptance/`: the unit tests
mock the browser, so they cannot show that the probe works. Here the browser really
runs, and every path the README lists is exercised on a copy of the caller's snapshot:

  1 pass                  the selector matches at both window sizes
  2 skip                  a second run with unchanged inputs runs no browser
  3 input drift           editing the copied site re-runs the stage
  4 output drift          editing report.json is caught and the stage runs again
  5 fail                  a broken snapshot is reported as fail, never as pass
  6 blocked               no browser on PATH is reported as blocked, never as pass
  7 skipped               --skip-browser is reported as skipped, never as pass
  8 symlinks              a link in the snapshot is refused and nothing is copied

Usage: verify_paths.py SNAPSHOT [--browser PATH] [--work DIR] [--json FILE]
Exit: 0 every path observed, 1 a path was not observed, 2 usage, 3 no browser (blocked).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CREATOR, PROBE = HERE / 'new_task.py', HERE / 'probe.py'
CANARY = 'CANARY-outside-the-snapshot'


def sh(*cmd, **kwargs):
    return subprocess.run([str(x) for x in cmd], capture_output=True, text=True, **kwargs)


class Paths:
    def __init__(self, work, browser):
        self.work, self.browser, self.results = work, browser, []

    # --- observation helpers -------------------------------------------------
    def task(self, name):
        return self.work / name

    def make(self, name, snapshot, *extra):
        if self.task(name).exists():
            shutil.rmtree(self.task(name))
        done = sh(sys.executable, CREATOR, snapshot, self.task(name), *extra)
        return done

    def run(self, name, env=None):
        given = dict(env or {})
        full = {**os.environ, **given}
        if self.browser and 'WEB_ACCEPTANCE_BROWSER' not in given:
            full['WEB_ACCEPTANCE_BROWSER'] = str(self.browser)
        return sh(sys.executable, '-m', 'makeextreme', 'run', self.task(name), cwd=str(REPO), env=full)

    def report(self, name):
        try:
            return json.loads((self.task(name) / 'report.json').read_text())
        except (OSError, ValueError):
            return None

    def journal(self, name):
        try:
            lines = (self.task(name) / 'journal.jsonl').read_text().splitlines()
        except OSError:
            return []
        return [json.loads(line) for line in lines if line.strip()]

    def events(self, name, kind):
        return [e for e in self.journal(name) if e.get('ev') == kind]

    def gate(self, name):
        probe = self.task(name) / 'probe.py'
        return sh(sys.executable, probe, 'check', cwd=str(self.task(name))).returncode

    def digest(self, name):
        try:
            return hashlib.sha256((self.task(name) / 'report.json').read_bytes()).hexdigest()
        except OSError:
            return 'missing'

    def check(self, path, ok, detail):
        self.results.append({'path': path, 'ok': bool(ok), 'detail': detail})
        print(f'{"PASS" if ok else "FAIL"}  {path:<22} {detail}')
        return bool(ok)

    def guard(self, name, fn, *args):
        """Run one path group. A path that raised is a path not observed: it is recorded as a
        failure with the exception, so one broken step cannot hide the steps that did run."""
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001 - the report is the point, not the traceback
            self.check(name, False, f'raised {type(exc).__name__}: {exc}')

    # --- the paths -----------------------------------------------------------
    def pass_path(self, snapshot):
        made = self.make('pass', snapshot)
        if not self.check('1 pass', made.returncode == 0, f'create task rc={made.returncode} {made.stderr.strip()[:120]}'):
            return
        done = self.run('pass')
        report = self.report('pass') or {}
        views = report.get('checks') or []
        states = [(v.get('requested'), v.get('viewport'), [s.get('ok') for s in v.get('states') or []]) for v in views]
        ok = (done.returncode == 0 and report.get('status') == 'pass' and len(views) == 2
              and all(all(flags) and len(flags) == 3 for _, _, flags in states)
              and report.get('browser', {}).get('sandbox') == 'enabled'
              and '--no-sandbox' not in (report.get('flags') or [])
              and self.gate('pass') == 0)
        browser = report.get('browser', {})
        self.check('1 pass', ok, f'rc={done.returncode} status={report.get("status")} '
                                f'browser={browser.get("version")} viewports={[v for _, v, _ in states]} '
                                f'gate={self.gate("pass")}')

    def skip_path(self):
        before = self.digest('pass')
        events = len(self.journal('pass'))
        done = self.run('pass')
        new = self.journal('pass')[events:]
        skipped = [e for e in new if e.get('ev') == 'skip']
        self.check('2 skip', done.returncode == 0 and bool(skipped) and self.digest('pass') == before,
                   f'rc={done.returncode} events={[e["ev"] for e in new]} report unchanged={self.digest("pass") == before}')

    def input_drift_path(self):
        site = self.task('pass') / 'site/index.html'
        site.write_text(site.read_text(encoding='utf-8') + '\n<!-- edited by verify_paths -->\n', encoding='utf-8')
        events = len(self.journal('pass'))
        done = self.run('pass')
        new = self.journal('pass')[events:]
        kinds = [e['ev'] for e in new]
        report = self.report('pass') or {}
        starts = self.events('pass', 'start')
        attempt = starts[-1]['attempt'] if starts else None
        self.check('3 input drift', done.returncode == 0 and 'invalidated' in kinds and 'start' in kinds
                   and report.get('status') == 'pass' and attempt == 2,
                   f'rc={done.returncode} events={kinds} attempt={attempt} status={report.get("status")}')

    def output_drift_path(self):
        report = self.report('pass') or {}
        views = report.get('checks') or []
        if not views or not views[0].get('states'):
            self.check('4 output drift', False, 'there is no finished pass report to tamper with')
            return
        report_file = self.task('pass') / 'report.json'
        report['checks'][0]['states'][1]['ok'] = False
        report_file.write_text(json.dumps(report, indent=2) + '\n')
        gate_on_tamper = self.gate('pass')
        events = len(self.journal('pass'))
        done = self.run('pass')
        new = self.journal('pass')[events:]
        kinds = [e['ev'] for e in new]
        reason = ' '.join(str(e.get('reason', '')) for e in new)
        after = self.report('pass') or {}
        restored = all(s.get('ok') for v in after.get('checks') or [] for s in v.get('states') or [])
        self.check('4 output drift', gate_on_tamper == 1 and done.returncode == 0 and 'invalidated' in kinds
                   and 'output changed since the stage finished' in reason and restored and self.gate('pass') == 0,
                   f'tampered gate={gate_on_tamper} rc={done.returncode} events={kinds} reason={reason[:60]!r} '
                   f'restored={restored}')

    def fail_path(self, snapshot):
        """Two real breakages of a temporary copy: a control that is gone, and a click that
        no longer reaches the page's handler. Both must be observed as `fail`."""
        broken = {}

        def gone(site):
            page = site / 'index.html'
            page.write_text(page.read_text(encoding='utf-8').replace(
                'data-digest="changed"', 'data-digest="changed-gone"', 1), encoding='utf-8')
            return True

        def deaf(site):
            page = site / 'index.html'
            page.write_text(page.read_text(encoding='utf-8').replace(
                '</body>', '<script>document.querySelector(\'[data-digest="changed"]\')'
                           ".addEventListener('click', e => e.stopImmediatePropagation(), true);"
                           '</script></body>', 1), encoding='utf-8')
            return True

        for name, transform in (('missing', gone), ('deaf', deaf)):
            site = self.work / f'broken-{name}'
            if site.exists():
                shutil.rmtree(site)
            shutil.copytree(snapshot, site, symlinks=True)
            if 'data-digest="changed"' not in (site / 'index.html').read_text(encoding='utf-8'):
                self.check(f'5 fail ({name})', False, 'the snapshot has no data-digest="changed" button to break')
                continue
            transform(site)
            made = self.make(f'fail-{name}', site)
            if made.returncode:
                self.check(f'5 fail ({name})', False, f'create task rc={made.returncode} {made.stderr.strip()[:120]}')
                continue
            done = self.run(f'fail-{name}')
            report = self.report(f'fail-{name}') or {}
            states = [(v.get('requested'), [(s.get('state'), s.get('ok')) for s in v.get('states') or []])
                      for v in report.get('checks') or []]
            bad = [s for _, ss in states for s in ss if s[1] is not True]
            end = self.events(f'fail-{name}', 'end')
            broken[name] = {'rc': done.returncode, 'status': report.get('status'), 'bad': len(bad),
                            'failure': end[-1].get('failure') if end else None,
                            'gate': self.gate(f'fail-{name}')}
            ok = (done.returncode == 2 and report.get('status') == 'fail' and bool(bad)
                  and self.gate(f'fail-{name}') == 1 and broken[name]['failure'] == 'check_failed')
            self.check(f'5 fail ({name})', ok,
                       f'rc={done.returncode} status={report.get("status")} failing states={len(bad)} '
                       f'failure={broken[name]["failure"]} gate={broken[name]["gate"]}')

    def blocked_path(self, snapshot):
        empty = self.work / 'empty-path'
        empty.mkdir(exist_ok=True)
        made = self.make('blocked', snapshot)
        if made.returncode:
            self.check('6 blocked', False, f'create task rc={made.returncode}')
            return
        done = self.run('blocked', env={'PATH': str(empty), 'WEB_ACCEPTANCE_BROWSER': ''})
        report = self.report('blocked') or {}
        end = self.events('blocked', 'end')
        self.check('6 blocked', done.returncode == 2 and report.get('status') == 'blocked'
                   and 'browser executable not found' in str(report.get('reason')) and self.gate('blocked') == 1,
                   f'PATH has no browser: rc={done.returncode} status={report.get("status")} '
                   f'reason={str(report.get("reason"))[:50]!r} gate={self.gate("blocked")} '
                   f'failure={end[-1].get("failure") if end else None}')

    def skipped_path(self, snapshot):
        made = self.make('skipped', snapshot, '--skip-browser')
        if made.returncode:
            self.check('7 skipped', False, f'create task rc={made.returncode}')
            return
        done = self.run('skipped')
        report = self.report('skipped') or {}
        self.check('7 skipped', done.returncode == 2 and report.get('status') == 'skipped' and self.gate('skipped') == 1,
                   f'--skip-browser: rc={done.returncode} status={report.get("status")} gate={self.gate("skipped")}')

    def symlink_path(self, snapshot):
        outside = self.work / 'outside'
        outside.mkdir(exist_ok=True)
        (outside / 'secret.txt').write_text(CANARY)
        (outside / 'asset.js').write_text(CANARY)
        cases, ok = [], True
        for name, link, target in (('index.html', 'index.html', outside / 'secret.txt'),
                                   ('asset', 'assets/copied-from-outside.txt', outside / 'asset.js'),
                                   ('dir', 'assets/more', outside)):
            site = self.work / f'link-{name}'
            shutil.copytree(snapshot, site, symlinks=False, ignore=shutil.ignore_patterns('.git'))
            target_path = site / link
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                shutil.rmtree(target_path) if target_path.is_dir() else target_path.unlink()
            target_path.symlink_to(target, target_is_directory=target.is_dir())
            made = self.make(f'link-task-{name}', site)
            cases.append({'case': name, 'rc': made.returncode, 'task_created': self.task(f'link-task-{name}').exists(),
                          'stderr': made.stderr.strip().splitlines()[-1][:110] if made.stderr.strip() else ''})
            ok = ok and made.returncode != 0 and 'symbolic link' in made.stderr \
                and not self.task(f'link-task-{name}').exists()
        real = self.work / 'linked-site'
        real.symlink_to(snapshot, target_is_directory=True)
        made = self.make('link-task-path', real)
        cases.append({'case': 'site path', 'rc': made.returncode, 'task_created': self.task('link-task-path').exists(),
                      'stderr': made.stderr.strip().splitlines()[-1][:110] if made.stderr.strip() else ''})
        ok = ok and made.returncode != 0 and 'symbolic link' in made.stderr and not self.task('link-task-path').exists()
        leaked = [str(p) for p in self.work.rglob('*')
                  if p.is_file() and not p.is_symlink() and outside.resolve() not in p.resolve().parents
                  and CANARY in p.read_text(errors='replace')]
        links = [str(p) for p in (self.task('pass') / 'site').rglob('*') if p.is_symlink()] \
            if (self.task('pass') / 'site').is_dir() else ['the copied site is missing']
        self.check('8 symlinks', ok and not leaked and not links,
                   f'refused={[c["case"] for c in cases if c["rc"]]}/{len(cases)} copied-outside={leaked} '
                   f'symlinks-in-copied-site={links}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('snapshot', type=Path, help='local dev-lu.com snapshot containing index.html')
    parser.add_argument('--browser', help='browser executable (default: first on PATH, or WEB_ACCEPTANCE_BROWSER)')
    parser.add_argument('--work', type=Path, help='directory for the tasks (default: a fresh temporary one)')
    parser.add_argument('--json', type=Path, help='write the result table here as JSON')
    parser.add_argument('--keep', action='store_true', help='keep the temporary work directory')
    a = parser.parse_args()
    if not (a.snapshot / 'index.html').is_file():
        sys.exit(f'{a.snapshot} has no index.html')
    browser = a.browser or os.environ.get('WEB_ACCEPTANCE_BROWSER') or next(
        (shutil.which(n) for n in ('chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable')
         if shutil.which(n)), None)
    if not browser:
        sys.exit('blocked: no browser executable found (set --browser or WEB_ACCEPTANCE_BROWSER)')
    work = a.work or Path(tempfile.mkdtemp(prefix='web-acceptance-paths-'))
    work.mkdir(parents=True, exist_ok=True)
    print(f'browser: {browser} ({sh(browser, "--version").stdout.strip()})')
    print(f'snapshot: {a.snapshot}\nwork: {work}\n')
    paths = Paths(work, browser)
    paths.guard('1 pass', paths.pass_path, a.snapshot)
    paths.guard('2 skip', paths.skip_path)
    paths.guard('3 input drift', paths.input_drift_path)
    paths.guard('4 output drift', paths.output_drift_path)
    paths.guard('5 fail', paths.fail_path, a.snapshot)
    paths.guard('6 blocked', paths.blocked_path, a.snapshot)
    paths.guard('7 skipped', paths.skipped_path, a.snapshot)
    paths.guard('8 symlinks', paths.symlink_path, a.snapshot)
    failed = [r for r in paths.results if not r['ok']]
    print(f'\n{len(paths.results) - len(failed)}/{len(paths.results)} paths observed')
    if a.json:
        a.json.write_text(json.dumps({'browser': browser, 'snapshot': str(a.snapshot),
                                      'results': paths.results}, indent=2) + '\n')
    if not a.keep and not a.work:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
