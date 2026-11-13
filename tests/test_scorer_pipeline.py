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
            self.reap_if_running(runner)

    GOOD = json.dumps({'score': 1, 'failure': None, 'expected': {}, 'got': {}, 'detail': 'matches'})

    def reap_if_running(self, runner):
        """Stop the runner under test and, if an assertion failed mid-stage, reap only this task's
        recorded run id / original group with the runner's own guard."""
        if runner.poll() is None:
            runner.kill()
            runner.wait(timeout=10)
        state_path = self.task_dir / 'task.json'
        if state_path.exists():
            stage = json.loads(state_path.read_text()).get('stages', {}).get('score', {})
            if stage.get('status') == 'running':
                from makeextreme.core import reap
                reap(stage)

    def test_a_stage_completed_before_the_kill_is_not_repeated_on_resume(self):
        """A crash records the stage that was running, not one next to it: the completed stage is
        skipped on resume and the interrupted one is retried once (no off-by-one resume position)."""
        d = str(self.task_dir)
        spec = json.loads(self.read(d, 'stages.json'))
        spec.insert(0, {'id': 'prepare', 'run': "printf 'prepared' > prep.txt",
                        'check': 'test -s prep.txt', 'deps': [], 'outputs': ['prep.txt'], 'timeout': 30})
        spec[1]['run'] = "if test ! -e held; then touch held; sleep 30; fi; " + spec[1]['run']
        self.write(d, 'stages.json', json.dumps(spec))
        self.write(d, 'reply.txt', self.GOOD)  # the reply is right; only the crash is under test
        runner = mx_start('run', d)
        try:
            self.assertTrue(wait_for(os.path.join(d, 'held')), 'score did not start')
            held = self.state(d)
            self.assertEqual(held['stages']['prepare']['status'], 'done')
            self.assertEqual(held['stages']['score']['status'], 'running')
            os.kill(runner.pid, signal.SIGKILL)
            runner.wait(timeout=10)
            crashed = self.state(d)
            self.assertEqual(crashed['stages']['score']['status'], 'running')  # recorded position
            self.assertNotIn('report', crashed['stages'])  # not advanced past the crash
            resumed = mx('run', d, timeout=60)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            state = self.state(d)
            self.assertEqual(state['status'], 'complete')
            self.assertEqual(state['stages']['prepare']['attempts'], 1)
            self.assertEqual(state['stages']['score']['attempts'], 2)
            self.assertEqual(state['stages']['report']['attempts'], 1)
            started = [e['stage'] for e in self.journal(d) if e['ev'] == 'start']
            self.assertEqual(started.count('prepare'), 1)  # once, ever: completed work is not redone
            self.assertIn('recovered_from_crash', self.events(d))
        finally:
            self.reap_if_running(runner)

    def test_sigterm_mid_score_records_the_position_and_resumes_to_complete(self):
        """The cron -15 case: exit 143, `interrupted` on the stage that was running and nowhere
        else, and the next run completes the task."""
        d = str(self.task_dir)
        spec = json.loads(self.read(d, 'stages.json'))
        spec[0]['run'] = "if test ! -e held; then touch held; sleep 30; fi; " + spec[0]['run']
        self.write(d, 'stages.json', json.dumps(spec))
        self.write(d, 'reply.txt', self.GOOD)
        runner = mx_start('run', d)
        try:
            self.assertTrue(wait_for(os.path.join(d, 'held')), 'score did not start')
            os.kill(runner.pid, signal.SIGTERM)
            self.assertEqual(runner.wait(timeout=10), 128 + signal.SIGTERM)
            state = self.state(d)
            self.assertEqual(state['status'], 'interrupted')
            self.assertEqual(state['stages']['score']['status'], 'interrupted')
            self.assertNotIn('report', state['stages'])
            resumed = mx('run', d, timeout=60)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            state = self.state(d)
            self.assertEqual(state['status'], 'complete')
            self.assertEqual((state['stages']['score']['attempts'],
                              state['stages']['report']['attempts']), (2, 1))
            self.assertIn('recovered_from_interrupt', self.events(d))
        finally:
            self.reap_if_running(runner)

    def test_a_killed_scorer_fails_the_stage_instead_of_accepting_its_output(self):
        """Infrastructure death is not a score: an empty score.json cannot pass the check, and the
        report does not run. Restoring the scorer and rerunning recovers without state surgery."""
        d = str(self.task_dir)
        self.scorer.write_text(
            "import os, pathlib, time\n"
            "pathlib.Path('scorer.pid').write_text(str(os.getpid()))\n"
            "time.sleep(30)\n")
        self.write(d, 'reply.txt', self.GOOD)  # a passing reply is on disk, but the scorer dies
        runner = mx_start('run', d)
        try:
            self.assertTrue(wait_for(os.path.join(d, 'scorer.pid')), 'scorer did not start')
            os.kill(int(self.read(d, 'scorer.pid')), signal.SIGKILL)
            self.assertEqual(runner.wait(timeout=60), 2)
            state = self.state(d)
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['stages']['score']['failure'], 'nonzero_exit')
            self.assertEqual(self.read(d, 'score.json'), '')
            self.assertNotIn('report', state['stages'])
            self.assertFalse((self.task_dir / 'accepted.json').exists())
            self.scorer.write_text("import pathlib, sys\n"
                                   "print(pathlib.Path(sys.argv[2]).read_text())\n")
            recovered = mx('run', d, timeout=30)
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            self.assertEqual(self.state(d)['status'], 'complete')
            self.assertTrue((self.task_dir / 'accepted.json').exists())
        finally:
            self.reap_if_running(runner)


if __name__ == '__main__':
    unittest.main()
