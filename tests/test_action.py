"""Exercise the composite action entry point without a GitHub runner."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from support import REPO

ROOT = Path(REPO)
EXAMPLE = ROOT / 'examples' / 'github-action'


class ActionEntry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='mx action ')
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        # Shell metacharacters and an initial dash must be a path, not code.
        self.name = '-task $(touch INJECTED)'
        self.task = self.workspace / self.name
        self.task.mkdir()
        self.env = dict(os.environ, GITHUB_WORKSPACE=str(self.workspace),
                        MAKEEXTREME_ACTION_PATH=str(ROOT), MAKEEXTREME_TASK_DIR=self.name)

    def run_action(self):
        return subprocess.run(['bash', str(ROOT / 'action' / 'run.sh')], cwd=self.workspace,
                              env=self.env, capture_output=True, text=True, timeout=20)

    def test_failure_resume_and_output_repair(self):
        for name in ('stages.json', 'seed.txt'):
            shutil.copyfile(EXAMPLE / name, self.task / name)
        # The action's module must win over a same-named caller-workspace package.
        shadow = self.workspace / 'makeextreme'
        shadow.mkdir()
        (shadow / '__init__.py').write_text('raise RuntimeError("wrong module")\n')
        first = self.run_action()
        self.assertEqual(first.returncode, 2, (first.stdout, first.stderr))
        self.assertFalse((self.task / 'report.txt').exists())
        (self.task / 'retry.flag').touch()
        second = self.run_action()
        self.assertEqual(second.returncode, 0, (second.stdout, second.stderr))
        check = subprocess.run([sys.executable, str(EXAMPLE / 'verify.py'), str(self.task)],
                               capture_output=True, text=True, timeout=10)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertFalse((self.workspace / 'INJECTED').exists())
        (self.task / 'report.txt').write_text('tampered\n')
        self.assertEqual(self.run_action().returncode, 0)
        self.assertEqual((self.task / 'report.txt').read_bytes(), (self.task / 'seed.txt').read_bytes())

    def test_missing_input_is_refused(self):
        self.env['MAKEEXTREME_TASK_DIR'] = ''
        self.assertEqual(self.run_action().returncode, 64)

    def test_approval_stage_failure_remains_uncertain(self):
        (self.task / 'artifact.txt').write_text('approved input\n')
        (self.task / 'stages.json').write_text(json.dumps([{
            'id': 'send', 'run': 'echo attempted >> attempts.txt; false', 'check': 'true',
            'deps': ['artifact.txt'], 'approval': 'required'}]))
        self.assertEqual(self.run_action().returncode, 4)
        approval = subprocess.run([sys.executable, '-m', 'makeextreme', 'approve',
                                   str(self.task), 'send'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(approval.returncode, 0, approval.stderr)
        self.assertEqual(self.run_action().returncode, 5)
        self.assertEqual(self.run_action().returncode, 5)
        self.assertEqual((self.task / 'attempts.txt').read_text().splitlines(), ['attempted'])
        state = json.loads((self.task / 'task.json').read_text())
        self.assertEqual(state['stages']['send']['status'], 'uncertain')


if __name__ == '__main__':
    unittest.main()
