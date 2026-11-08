import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from makeextreme.budget import assess
ROOT = Path(__file__).resolve().parents[1]

class Budget(unittest.TestCase):
    def setUp(self):
        self.plan = {'version': 1, 'attempts_used': 0, 'max_attempts': 3, 'retry_reserve': 1,
                     'resources': {'seconds': {'remaining': 10, 'attempt': 3, 'recovery': 1, 'verification': 3}}}

    def test_exact_boundary(self):
        self.assertTrue(assess(self.plan)['admit'])
        self.assertEqual(assess(self.plan)['resources']['seconds']['headroom'], 0)

    def test_verification_reserve(self):
        self.plan['resources']['seconds']['remaining'] = 9
        self.assertFalse(assess(self.plan)['admit'])

    def test_attempt_reserve(self):
        self.plan['attempts_used'] = 2
        self.assertIn('attempt_limit', assess(self.plan)['reasons'])

    def test_unknown_never_admits(self):
        for key in ('remaining', 'attempt', 'recovery', 'verification'):
            plan = copy.deepcopy(self.plan)
            plan['resources']['seconds'][key] = None
            self.assertFalse(assess(plan)['admit'])

    def test_dimensions_not_combined(self):
        self.plan['resources']['calls'] = dict(remaining=0, attempt=1, recovery=0, verification=0)
        self.assertFalse(assess(self.plan)['admit'])

    def test_reject_bad_numbers_and_shapes(self):
        for value in (-1, True, 1.5, float('nan'), float('inf'), '10'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                plan = copy.deepcopy(self.plan)
                plan['resources']['seconds']['remaining'] = value
                assess(plan)
        for plan in ({}, [], dict(self.plan, version=True), dict(self.plan, resources={})):
            with self.assertRaises(ValueError):
                assess(plan)

    def test_declared_budget_is_not_mutated(self):
        original = copy.deepcopy(self.plan)
        assess(self.plan)
        self.assertEqual(self.plan, original)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'plan.json'
            for data, expected in [(self.plan, 0), (dict(self.plan, max_attempts=0), 2), ({}, 64)]:
                path.write_text(json.dumps(data))
                p = subprocess.run([sys.executable, '-m', 'makeextreme.budget', str(path)], cwd=ROOT, capture_output=True)
                self.assertEqual(p.returncode, expected, p.stderr)

    def test_stage_preflight_blocks_then_admits(self):
        import shlex
        with tempfile.TemporaryDirectory() as d:
            task = Path(d)
            plan = copy.deepcopy(self.plan)
            plan['resources']['seconds']['remaining'] = 9
            (task/'budget.json').write_text(json.dumps(plan))
            checker = ROOT/'makeextreme/budget.py'
            command = f'{shlex.quote(sys.executable)} {shlex.quote(str(checker))} budget.json && echo checked > out.txt'
            stages = [{'id': 'work', 'run': command, 'check': 'test -s out.txt',
                       'deps': ['budget.json', str(checker)], 'outputs': ['out.txt']}]
            (task/'stages.json').write_text(json.dumps(stages))
            def run():
                return subprocess.run([sys.executable, '-m', 'makeextreme', 'run', str(task)], cwd=ROOT, capture_output=True)
            self.assertEqual(run().returncode, 2)
            self.assertFalse((task/'out.txt').exists())
            plan['resources']['seconds']['remaining'] = 10
            (task/'budget.json').write_text(json.dumps(plan))
            result = run()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((task/'out.txt').read_text(), 'checked\n')

    def test_paired_experiment(self):
        p = subprocess.run([sys.executable, str(ROOT/'examples/recovery_budget/compare.py')], capture_output=True, text=True, check=True)
        data = json.loads(p.stdout)
        self.assertEqual(data['baseline']['completed'], 14)
        self.assertEqual(data['reserve']['completed'], 14)
        self.assertEqual(data['baseline']['unverified_outputs'], 1)
        self.assertEqual(data['reserve']['unverified_outputs'], 0)
        self.assertLess(data['reserve']['total_spent'], data['baseline']['total_spent'])

if __name__ == '__main__':
    unittest.main()
