"""examples/cron_tick.sh: a tick starts the worker and reports; it never decides (decision 5A)."""
import fcntl
import os
import subprocess
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


if __name__ == "__main__":
    unittest.main()
