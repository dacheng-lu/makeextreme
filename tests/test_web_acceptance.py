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
spec = importlib.util.spec_from_file_location('web_probe', PROBE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

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

    def test_snapshot_symlinks_are_refused_without_copying(self):
        creator = ROOT / 'examples/web_acceptance/new_task.py'
        for linked in ('index.html', 'asset', 'dir'):
            with self.subTest(linked=linked):
                site = Path('input-' + linked)
                site.mkdir()
                outside = Path('outside-' + linked).resolve()
                if linked == 'dir':
                    outside.mkdir()
                else:
                    outside.write_text('outside')
                if linked != 'index.html':
                    (site / 'index.html').write_text('<html></html>')
                (site / linked).symlink_to(outside, target_is_directory=linked == 'dir')
                task = Path('task-' + linked)
                result = subprocess.run([sys.executable, str(creator), str(site), str(task)],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('symbolic link', result.stderr)
                self.assertFalse(task.exists())

    def test_browser_observations_gate_and_output_drift(self):
        def fake_browser(*args, **kwargs):
            checks = [{'state': s, 'ok': True} for s in ('checked', 'changed', 'restored')]
            return subprocess.CompletedProcess(args, 0, '<pre id="acceptance-result">' + json.dumps({'checks': checks}) + '</pre>', '')
        with mock.patch.object(probe.shutil, 'which', return_value='/fake/chromium'), mock.patch.object(probe.subprocess, 'run', side_effect=fake_browser):
            probe.run()
        self.assertEqual(json.loads(Path('report.json').read_text())['status'], 'pass')
        self.assertEqual(self.gate(), 0)
        report = json.loads(Path('report.json').read_text())
        report['checks'][0]['states'][1]['ok'] = False
        Path('report.json').write_text(json.dumps(report))
        self.assertNotEqual(self.gate(), 0)

    def test_failed_observation_is_not_pass(self):
        checks = [{'state': s, 'ok': s != 'changed'} for s in ('checked', 'changed', 'restored')]
        result = subprocess.CompletedProcess([], 0, '<pre id="acceptance-result">' + json.dumps({'checks': checks}) + '</pre>', '')
        with mock.patch.object(probe.shutil, 'which', return_value='/fake/chromium'), mock.patch.object(probe.subprocess, 'run', return_value=result):
            probe.run()
        self.assertEqual(json.loads(Path('report.json').read_text())['status'], 'fail')
        self.assertNotEqual(self.gate(), 0)

    def test_missing_browser_and_explicit_skip_do_not_pass(self):
        with mock.patch.object(probe.shutil, 'which', return_value=None): probe.run()
        self.assertEqual(json.loads(Path('report.json').read_text())['status'], 'blocked')
        self.assertNotEqual(self.gate(), 0)
        subprocess.run([sys.executable, str(PROBE), 'skip'], check=True)
        self.assertEqual(json.loads(Path('report.json').read_text())['status'], 'skipped')
        self.assertNotEqual(self.gate(), 0)

if __name__ == '__main__': unittest.main()
