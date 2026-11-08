import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'examples/audit_ladder/records'

def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

records = load('audit_records')
generator = load('new_task')

class AuditRecords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle = self.root / 'bundle'
        (self.bundle / 'evidence').mkdir(parents=True)
        log = self.bundle / 'evidence/check.txt'
        log.write_text('fixture observation, not a security finding\n')
        self.scope = {'base': 'a' * 40, 'head': 'b' * 40}
        self.ref = {'path': 'evidence/check.txt', 'sha256': records.digest(log)}
        self.data = {'version': 1, 'scope': self.scope,
                     'coverage': [{'id': 'boundary', 'status': 'checked', 'evidence': [self.ref]}],
                     'findings': [{'id': 'F1', 'unit': 'boundary', 'verdict': 'rejected',
                                   'author': 'hunter', 'reviewer': 'verifier', 'reason': 'fixture disproved',
                                   'severity': None, 'evidence': [self.ref]}]}
        (self.bundle / 'scope.json').write_text(json.dumps(self.scope))
        self.write()

    def write(self):
        (self.bundle / 'records.json').write_text(json.dumps(self.data))

    def test_valid(self):
        self.assertEqual(records.validate(self.bundle), self.data)

    def test_negative_records(self):
        mutations = [
            lambda d: d.update(version=2),
            lambda d: d.update(coverage=[]),
            lambda d: d['coverage'].append(copy.deepcopy(d['coverage'][0])),
            lambda d: d['coverage'][0].update(evidence=[]),
            lambda d: d['findings'][0].update(reviewer='hunter'),
            lambda d: d['findings'][0].update(verdict='needs_validation', severity='high'),
            lambda d: d['findings'][0].update(unit='missing'),
            lambda d: d['findings'][0].update(verdict='passed'),
            lambda d: d['scope'].update(head='c' * 40),
            lambda d: d['findings'][0]['evidence'][0].update(path='../outside'),
        ]
        original = copy.deepcopy(self.data)
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.data = copy.deepcopy(original)
                mutate(self.data)
                self.write()
                with self.assertRaises(ValueError):
                    records.validate(self.bundle)

    def test_stale_evidence(self):
        (self.bundle / 'evidence/check.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'stale'):
            records.validate(self.bundle)

    def test_unresolved_is_reported_not_confirmed(self):
        self.data['findings'][0].update(verdict='needs_validation', reviewer=None)
        self.write()
        output = records.report(records.validate(self.bundle))
        self.assertIn('needs_validation: 1', output)
        self.assertIn('confirmed: 0', output)

    def run_task(self, task):
        return subprocess.run([sys.executable, '-m', 'makeextreme', 'run', str(task)], cwd=ROOT, capture_output=True, text=True, timeout=30)

    def test_runner_resume_drift_and_scope(self):
        task = self.root / 'task'
        generator.create(self.bundle, task)
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stderr)
        first = (task / 'report.md').read_bytes()
        self.assertEqual(self.run_task(task).returncode, 0)
        events = [json.loads(x) for x in (task / 'journal.jsonl').read_text().splitlines()]
        self.assertEqual(sum(e.get('ev') == 'start' for e in events), 2)
        (task / 'report.md').write_text('forged report')
        self.assertEqual(self.run_task(task).returncode, 0)
        self.assertEqual((task / 'report.md').read_bytes(), first)
        (task / 'scope.json').write_text(json.dumps(dict(self.scope, head='c' * 40)))
        self.assertNotEqual(self.run_task(task).returncode, 0)

    def test_existing_target_refused(self):
        with self.assertRaises(FileExistsError):
            generator.create(self.bundle, self.bundle)

if __name__ == '__main__':
    unittest.main()
