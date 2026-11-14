"""Regression checks for the optional web probe's outcomes and stage gate."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'examples/web_acceptance/probe.py'
CREATOR = ROOT / 'examples/web_acceptance/new_task.py'
spec = importlib.util.spec_from_file_location('web_probe', PROBE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def observation(width, height, ok=True):
    """What the injected page script would report for a window of this size: Chrome renders
    a request narrower than 500px at 500px, and it trims 143px of height off the window."""
    states = [{'state': s, 'ok': ok} for s in probe.STATES]
    return json.dumps({'viewport': [max(width, 500), height - 143], 'checks': states})


class FakeBrowser:
    """Stands in for the browser process: answers --version and --dump-dom like Chrome does."""

    def __init__(self, width_seen=None, ok=True):
        self.calls, self.width_seen, self.ok = [], width_seen, ok

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if '--version' in cmd:
            return subprocess.CompletedProcess(cmd, 0, 'Fake Chrome 157.0\n', '')
        width, height = next(a.split('=')[1].split(',') for a in cmd if a.startswith('--window-size='))
        seen = (self.width_seen or {}).get(int(width), int(width))
        text = observation(seen, int(height), self.ok)
        return subprocess.CompletedProcess(cmd, 0, '<pre id="acceptance-result">' + text + '</pre>', '')


class WebProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = Path.cwd()
        os.chdir(self.tmp.name)
        Path('site').mkdir()
        Path('site/index.html').write_text('<html><body></body></html>')

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def gate(self):
        return subprocess.run([sys.executable, str(PROBE), 'check']).returncode

    def report(self):
        return json.loads(Path('report.json').read_text())

    def probe_with(self, browser, which='/fake/chromium', env=None):
        with mock.patch.object(probe.shutil, 'which', return_value=which), \
             mock.patch.object(probe.subprocess, 'run', side_effect=browser), \
             mock.patch.dict(os.environ, env or {}, clear=False):
            probe.run()

    def test_snapshot_symlinks_are_refused_without_copying(self):
        root = Path(self.tmp.name)
        for linked in ('index.html', 'asset', 'dir'):
            with self.subTest(linked=linked):
                work = root / ('case-' + linked)
                work.mkdir()
                outside = root / ('outside-' + linked)
                if linked == 'dir':
                    outside.mkdir()
                    (outside / 'secret.txt').write_text('CANARY-' + linked)
                else:
                    outside.write_text('CANARY-' + linked)
                site = work / 'snapshot'
                site.mkdir()
                if linked != 'index.html':
                    (site / 'index.html').write_text('<html></html>')
                (site / linked).symlink_to(outside, target_is_directory=linked == 'dir')
                task = work / 'task'
                result = subprocess.run([sys.executable, str(CREATOR), str(site), str(task)],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('symbolic link', result.stderr)
                self.assertFalse(task.exists(), 'nothing may be created for a refused snapshot')
                for path in work.rglob('*'):
                    if path.is_file() and not path.is_symlink() and site not in path.parents:
                        self.assertNotIn('CANARY-', path.read_text(errors='replace'), path)

    def test_only_the_snapshot_is_copied(self):
        Path('outside.txt').write_text('CANARY-outside')
        Path('site/assets').mkdir()
        (Path('site/assets') / 'logo.svg').write_text('<svg></svg>')
        result = subprocess.run([sys.executable, str(CREATOR), 'site', 'task-clean'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        copied = sorted(p.relative_to('task-clean/site').as_posix()
                        for p in Path('task-clean/site').rglob('*') if p.is_file())
        self.assertEqual(copied, ['assets/logo.svg', 'index.html'])
        for path in Path('task-clean/site').rglob('*'):
            self.assertFalse(path.is_symlink(), path)
            if path.is_file():
                self.assertNotIn('CANARY-', path.read_text(errors='replace'), path)

    def test_a_symlinked_site_path_is_refused(self):
        real = Path('real-site'); real.mkdir()
        (real / 'index.html').write_text('<html></html>')
        Path('linked-site').symlink_to(real, target_is_directory=True)
        result = subprocess.run([sys.executable, str(CREATOR), 'linked-site', 'task-linked'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('symbolic link', result.stderr)
        self.assertFalse(Path('task-linked').exists())

    def test_the_git_entry_of_a_snapshot_is_not_copied(self):
        Path('site/.git').mkdir()
        Path('site/.git/config').write_text('[core]\n')
        result = subprocess.run([sys.executable, str(CREATOR), 'site', 'task-git'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(Path('task-git/site/index.html').is_file())
        self.assertFalse(Path('task-git/site/.git').exists())

    def test_browser_observations_gate_and_output_drift(self):
        self.probe_with(FakeBrowser())
        report = self.report()
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(report['browser'], {'path': '/fake/chromium', 'version': 'Fake Chrome 157.0',
                                             'sandbox': 'enabled'})
        self.assertEqual([v['viewport'] for v in report['checks']], [[1280, 657], [500, 701]])
        self.assertEqual(self.gate(), 0)
        report['checks'][0]['states'][1]['ok'] = False
        Path('report.json').write_text(json.dumps(report))
        self.assertNotEqual(self.gate(), 0)

    def test_failed_observation_is_not_pass(self):
        self.probe_with(FakeBrowser(ok=False))
        self.assertEqual(self.report()['status'], 'fail')
        self.assertNotEqual(self.gate(), 0)

    def test_missing_browser_and_explicit_skip_do_not_pass(self):
        self.probe_with(FakeBrowser(), which=None)
        self.assertEqual(self.report()['status'], 'blocked')
        self.assertNotEqual(self.gate(), 0)
        subprocess.run([sys.executable, str(PROBE), 'skip'], check=True)
        self.assertEqual(self.report()['status'], 'skipped')
        self.assertNotEqual(self.gate(), 0)

    def test_the_launch_keeps_the_browser_sandbox(self):
        browser = FakeBrowser()
        self.probe_with(browser)
        launches = [c for c in browser.calls if '--dump-dom' in c]
        self.assertEqual(len(launches), 2)
        for cmd in launches:
            self.assertNotIn('--no-sandbox', cmd)
            self.assertTrue(any(a.startswith('--user-data-dir=') for a in cmd))
            self.assertIn('--host-resolver-rules=MAP * ~NOTFOUND', cmd)
        self.assertNotIn('--no-sandbox', self.report()['flags'])

    def test_a_window_the_page_did_not_really_get_fails_the_gate(self):
        # the narrow request rendered 900px wide: the mobile layout was not exercised
        self.probe_with(FakeBrowser(width_seen={390: 900}))
        report = self.report()
        self.assertEqual(report['status'], 'fail')
        self.assertIn('900px', report['reason'])
        self.assertTrue(all(s['ok'] for v in report['checks'] for s in v['states']))
        self.assertNotEqual(self.gate(), 0)

    def test_the_browser_can_be_chosen_and_a_missing_one_is_blocked(self):
        self.probe_with(FakeBrowser(), which='/pinned/chrome',
                        env={'WEB_ACCEPTANCE_BROWSER': '/pinned/chrome'})
        self.assertEqual(self.report()['browser']['path'], '/pinned/chrome')
        self.probe_with(FakeBrowser(), which=None, env={'WEB_ACCEPTANCE_BROWSER': 'no-such-browser'})
        report = self.report()
        self.assertEqual(report['status'], 'blocked')
        self.assertIn('no-such-browser', report['reason'])

    def test_a_report_that_names_no_browser_or_a_disabled_sandbox_does_not_pass(self):
        self.probe_with(FakeBrowser())
        self.assertEqual(self.gate(), 0)
        good = self.report()
        for change in ({'browser': {}}, {'flags': [*good['flags'], '--no-sandbox']},
                       {'browser': {**good['browser'], 'sandbox': 'disabled'}}):
            with self.subTest(change=change):
                Path('report.json').write_text(json.dumps({**good, **change}))
                self.assertNotEqual(self.gate(), 0)


if __name__ == '__main__':
    unittest.main()
