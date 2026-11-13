"""The saved-reply pipeline must check a scorer that exits zero for a wrong answer."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

from support import REPO, TaskCase, mx, mx_start, wait_for


class ScorerPipeline(TaskCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mx-scoring-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        flow, longhaul = root / 'flow lore', root / 'long haul'
        # The stub implements only the CLI contract. The native scorer itself is
        # exercised by the separate offline command in the example README.
        scorer = flow / 'examples/local-model-baseline/scorer.py'
        scorer.parent.mkdir(parents=True)
        scorer.write_text("import pathlib, sys\n"
                          "text = pathlib.Path(sys.argv[2]).read_text()\n"
                          "if text == 'infrastructure error': sys.exit(9)\n"
                          "print(text)\n")
        for path in (flow / 'examples/local-model-baseline/scenarios.py',
                     flow / 'examples/release-digest/digest.py',
                     longhaul / 'scripts/checkpoint.py', longhaul / 'scripts/secret_scan.py'):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# fixture\n')
        reply = root / 'candidate.json'
        reply.write_text(json.dumps({'score': 0, 'failure': 'wrong_answer',
                                     'expected': {}, 'got': {}, 'detail': 'wrong'}))
        self.task_dir = root / 'task with spaces'
        setup = subprocess.run([sys.executable, os.path.join(REPO, 'examples/scorer_pipeline/new_task.py'),
                                str(self.task_dir), '--flowlore', str(flow), '--longhaul', str(longhaul),
                                '--case', 'g-pass', '--reply', str(reply)],
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(setup.returncode, 0, setup.stderr)
        self.scorer = scorer

    def test_interrupted_score_is_retried_but_wrong_result_still_blocks_the_report(self):
        d = str(self.task_dir)
        # Test-only fault injection holds the first scoring attempt at a known
        # point. The scorer, checks, dependencies and report stay unchanged.
        spec = json.loads(self.read(d, 'stages.json'))
        spec[0]['run'] = "if test ! -e held; then touch held; sleep 30; fi; " + spec[0]['run']
        self.write(d, 'stages.json', json.dumps(spec))
        runner = mx_start('run', d)
        try:
            self.assertTrue(wait_for(os.path.join(d, 'held')), 'score did not start')
            self.assertEqual(self.state(d)['stages']['score']['status'], 'running')
            os.kill(runner.pid, signal.SIGKILL)
            runner.wait(timeout=10)
            failed = mx('run', d, timeout=30)
            self.assertEqual(failed.returncode, 2, failed.stderr)
            state = self.state(d)
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['stages']['score']['attempts'], 2)
            self.assertEqual(state['stages']['score']['failure'], 'check_failed')
            self.assertEqual(json.loads(self.read(d, 'score.json'))['score'], 0)
            self.assertNotIn('report', state['stages'])
            self.assertFalse((self.task_dir / 'accepted.json').exists())
            self.assertIn('recovered_from_crash', self.events(d))
            end = [e for e in self.journal(d) if e['ev'] == 'end' and e['stage'] == 'score'][-1]
            self.assertEqual(end['rc'], 0)  # native CLI behaviour; not acceptance
            self.assertNotEqual(end['check_rc'], 0)

            self.write(d, 'reply.txt', json.dumps({'score': 1, 'failure': None,
                                                   'expected': {}, 'got': {}, 'detail': 'matches'}))
            passed = mx('run', d, timeout=30)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            state = self.state(d)
            self.assertEqual((state['status'], state['stages']['score']['attempts'],
                              state['stages']['report']['attempts']), ('complete', 3, 1))
            record = json.loads(self.read(d, 'accepted.json'))
            self.assertEqual(record['case'], 'g-pass')
            self.assertEqual(record['evaluation']['score'], 1)
            self.assertEqual(mx('run', d, timeout=30).returncode, 0)
            self.assertEqual(self.state(d)['stages']['score']['attempts'], 3)

            # A changed scorer must invalidate the old result and provenance.
            self.scorer.write_text(self.scorer.read_text() + '# changed\n')
            self.assertEqual(mx('run', d, timeout=30).returncode, 0)
            self.assertEqual(self.state(d)['stages']['score']['attempts'], 4)
            self.assertEqual(self.state(d)['stages']['report']['attempts'], 2)
            self.assertNotEqual(record['source_sha256']['scorer'],
                                json.loads(self.read(d, 'accepted.json'))['source_sha256']['scorer'])

            config = json.loads(self.read(d, 'config.json'))
            config['case'] = 'a-different-case'
            self.write(d, 'config.json', json.dumps(config))
            self.assertEqual(mx('run', d, timeout=30).returncode, 2)
            self.assertEqual(self.state(d)['status'], 'failed')
            self.assertEqual(self.read(d, 'score.json'), '')
            config['case'] = 'g-pass'
            self.write(d, 'config.json', json.dumps(config, indent=2) + '\n')

            self.write(d, 'reply.txt', 'infrastructure error')
            self.assertEqual(mx('run', d, timeout=30).returncode, 2)
            state = self.state(d)
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['stages']['score']['failure'], 'nonzero_exit')
            self.assertEqual(self.read(d, 'score.json'), '')  # no old score masquerades as new
        finally:
            if runner.poll() is None:
                runner.kill()
                runner.wait(timeout=10)
            # If an assertion fails before recovery, reap only this task's
            # recorded run id / original group, using the runner's own guard.
            state_path = self.task_dir / 'task.json'
            if state_path.exists():
                state = json.loads(state_path.read_text())
                stage = state.get('stages', {}).get('score', {})
                if stage.get('status') == 'running':
                    from makeextreme.core import reap
                    reap(stage)


if __name__ == '__main__':
    unittest.main()
