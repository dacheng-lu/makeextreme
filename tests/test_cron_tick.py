"""examples/cron_tick.sh: a tick starts the worker and reports; it never decides (decision 5A)."""
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import unittest

from support import REPO, TaskCase

TICK = os.path.join(REPO, "examples", "cron_tick.sh")


def tick(d):
    return subprocess.run(["sh", TICK, d], capture_output=True, text=True)


class CronTick(TaskCase):
    def test_a_tick_completes_the_task_and_a_second_tick_repeats_nothing(self):
        d = self.task([{"id": "s", "run": "echo x >> out.txt", "check": "test -s out.txt"}])
        first = tick(d)
        self.assertEqual((first.returncode, first.stdout.strip()), (0, "makeextreme: complete"), first.stderr)
        second = tick(d)
        self.assertEqual((second.returncode, second.stdout.strip()), (0, "makeextreme: complete"))
        self.assertEqual(self.read(d, "out.txt"), "x\n", "the second tick ran the stage again")

    def test_a_tick_while_a_runner_holds_the_lock_is_busy_and_changes_nothing(self):
        d = self.task([{"id": "s", "run": "echo x >> out.txt", "check": "test -s out.txt"}])
        with open(os.path.join(d, "lock"), "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)  # what a live runner does
            res = tick(d)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("busy", res.stdout)
        self.assertFalse(os.path.exists(os.path.join(d, "out.txt")), "a busy tick ran the stage")

    def test_a_tick_reports_an_approval_wait_without_failing_and_never_approves(self):
        d = self.task([{"id": "send", "run": "echo pay >> pay.out", "check": "test -s pay.out", "deps": ["art"],
                        "approval": "required"}], {"art": "A\n"})
        res = tick(d)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("waiting for approval", res.stdout)
        self.assertIn("approve", res.stdout)
        self.assertFalse(os.path.exists(os.path.join(d, "pay.out")))
        self.assertFalse(os.path.exists(os.path.join(d, "approvals.jsonl")), "a tick wrote an approval")

    def test_a_failed_stage_is_reported_and_the_next_tick_retries_it(self):
        d = self.task([{"id": "s", "run": "if test -f go; then echo ok > out.txt; fi", "check": "test -s out.txt"}])
        res = tick(d)
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("next tick retries", res.stdout)
        self.write(d, "go", "")
        res = tick(d)
        self.assertEqual((res.returncode, res.stdout.strip()), (0, "makeextreme: complete"), res.stderr)

    def test_an_uncertain_approval_stage_is_reported_for_a_human_and_not_repeated(self):
        d = self.task([{"id": "send", "run": "echo pay >> pay.out; exit 1", "check": "true", "deps": ["art"],
                        "approval": "required"}], {"art": "A\n"})
        tick(d)
        from support import mx
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        res = tick(d)
        self.assertEqual(res.returncode, 5, res.stdout + res.stderr)
        self.assertIn("resolve", res.stdout)
        again = tick(d)
        self.assertEqual(again.returncode, 5)
        self.assertEqual(self.read(d, "pay.out"), "pay\n", "a tick repeated the irreversible command")

    def test_a_relative_task_path_works_from_any_directory(self):
        """cron starts in $HOME and the script changes into the repository: the task path must be made absolute first."""
        d = self.task([{"id": "s", "run": "echo x >> out.txt", "check": "test -s out.txt"}])
        res = subprocess.run(["sh", TICK, os.path.basename(d)], capture_output=True, text=True, cwd=os.path.dirname(d))
        self.assertEqual((res.returncode, res.stdout.strip()), (0, "makeextreme: complete"), res.stdout + res.stderr)
        self.assertEqual(self.read(d, "out.txt"), "x\n")

    def test_a_missing_task_directory_is_refused_cleanly(self):
        res = subprocess.run(["sh", TICK, "/nonexistent/task"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 64)
        self.assertNotIn("Traceback", res.stderr)


class CronTickEntryPoints(TaskCase):
    """Found by the D19 audit (2026-11-01): how the script is started and what it tells the human."""

    STAGE = {"id": "s", "run": "echo x >> out.txt", "check": "test -s out.txt"}

    def test_a_tick_started_through_a_symlink_to_the_script_still_finds_the_package(self):
        d = self.task([self.STAGE])
        links = tempfile.TemporaryDirectory(prefix="bin-")
        self.addCleanup(links.cleanup)
        link = os.path.join(links.name, "tick")
        os.symlink(TICK, link)
        res = subprocess.run(["sh", link, d], capture_output=True, text=True, cwd=links.name)
        self.assertEqual((res.returncode, res.stdout.strip()), (0, "makeextreme: complete"), res.stdout + res.stderr)
        self.assertEqual(self.read(d, "out.txt"), "x\n")

    def test_a_missing_or_unusable_interpreter_is_not_reported_as_a_refused_task(self):
        d = self.task([self.STAGE])
        bogus = os.path.join(d, "not-executable")
        open(bogus, "w").write("#!/bin/sh\n")
        for py in ("/nonexistent/python3", "no-such-interpreter-xyz", bogus):
            res = subprocess.run(["sh", TICK, d], capture_output=True, text=True, env=dict(os.environ, PYTHON=py))
            self.assertEqual(res.returncode, 69, (py, res.stdout, res.stderr))
            self.assertIn("no usable python interpreter: " + py, res.stderr)
            self.assertNotIn("refused", res.stdout + res.stderr, py)
            self.assertNotIn("Traceback", res.stderr)
        self.assertFalse(os.path.exists(os.path.join(d, "task.json")), "nothing may run when the interpreter is unusable")

    def test_the_header_documents_exit_69_next_to_the_other_codes(self):
        header = [l for l in open(TICK, encoding="utf-8").read().splitlines() if l.startswith("#")]
        self.assertTrue(any("69" in l for l in header), header)

    def test_the_advice_for_a_waiting_approval_can_be_pasted_into_a_shell_even_for_an_awkward_path(self):
        parent = tempfile.TemporaryDirectory(prefix="adv-")
        self.addCleanup(parent.cleanup)
        d = os.path.join(parent.name, "my task's dir")
        os.makedirs(d)
        with open(os.path.join(d, "stages.json"), "w") as f:
            json.dump([{"id": "send", "run": "echo pay >> pay.out", "check": "test -s pay.out", "deps": ["art"], "approval": "required"}], f)
        self.write(d, "art", "A\n")
        res = subprocess.run(["sh", TICK, d], capture_output=True, text=True, env=dict(os.environ, PYTHON=sys.executable))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        advice = res.stdout.strip().split("waiting for approval: ", 1)[1]
        self.assertTrue(advice.startswith("cd '"), advice)
        run = subprocess.run(["sh", "-c", advice.replace("<stage>", "send")], capture_output=True, text=True, cwd=tempfile.gettempdir())
        self.assertEqual(run.returncode, 0, (advice, run.stdout, run.stderr))
        self.assertTrue(os.path.exists(os.path.join(d, "approvals.jsonl")), "the printed advice did not approve the stage")

    def test_the_advice_can_be_pasted_when_the_interpreter_path_contains_a_space(self):
        """Found by the audit of 1.1.1: the task path was quoted, the interpreter was not (a virtualenv under a path with a space)."""
        parent = tempfile.TemporaryDirectory(prefix="adv-")
        self.addCleanup(parent.cleanup)
        wrapper_dir = os.path.join(parent.name, "my py")
        os.makedirs(wrapper_dir)
        wrapper = os.path.join(wrapper_dir, "python3")
        with open(wrapper, "w") as f:
            f.write('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable)
        os.chmod(wrapper, 0o755)
        d = self.task([{"id": "send", "run": "echo pay >> pay.out", "check": "test -s pay.out", "deps": ["art"], "approval": "required"}], {"art": "A\n"})
        res = subprocess.run(["sh", TICK, d], capture_output=True, text=True, env=dict(os.environ, PYTHON=wrapper))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        advice = res.stdout.strip().split("waiting for approval: ", 1)[1].replace("<stage>", "send")
        run = subprocess.run(["sh", "-c", advice], capture_output=True, text=True, cwd=tempfile.gettempdir())
        self.assertEqual(run.returncode, 0, (advice, run.stdout, run.stderr))
        self.assertTrue(os.path.exists(os.path.join(d, "approvals.jsonl")), "the printed advice did not approve the stage")

    def test_a_relative_task_directory_whose_name_starts_with_a_dash_is_found(self):
        parent = tempfile.TemporaryDirectory(prefix="dash-")
        self.addCleanup(parent.cleanup)
        d = os.path.join(parent.name, "-t")
        os.makedirs(d)
        with open(os.path.join(d, "stages.json"), "w") as f:
            json.dump([self.STAGE], f)
        res = subprocess.run(["sh", TICK, "-t"], capture_output=True, text=True, cwd=parent.name, env=dict(os.environ, PYTHON=sys.executable))
        self.assertEqual((res.returncode, res.stdout.strip()), (0, "makeextreme: complete"), res.stdout + res.stderr)

    def test_the_advice_for_an_uncertain_stage_names_the_repository_and_quotes_the_task(self):
        d = self.task([{"id": "send", "run": "echo pay >> pay.out; exit 1", "check": "true", "deps": ["art"], "approval": "required"}], {"art": "A\n"})
        env = dict(os.environ, PYTHON=sys.executable)
        subprocess.run(["sh", TICK, d], capture_output=True, text=True, env=env)
        from support import mx
        mx("approve", d, "send")
        res = subprocess.run(["sh", TICK, d], capture_output=True, text=True, env=env)
        self.assertEqual(res.returncode, 5, res.stdout + res.stderr)
        self.assertIn("cd '" + REPO + "' && ", res.stdout)
        self.assertIn("resolve '" + d + "' send", res.stdout.replace("<stage>", "send"))


if __name__ == "__main__":
    unittest.main()
