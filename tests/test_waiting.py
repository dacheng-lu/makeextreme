"""A stage that must ask a human: it leaves `question.json`, the runner waits (exit 7) and never repeats it (D23).

The question is an artifact like any other: the state of the stage is read from the file, not from an exit
code, and the text never enters the record — a question may quote a token, and the record must stay clean.
"""
import os
import subprocess
import unittest

from support import REPO, TaskCase, mx

TICK = os.path.join(REPO, "examples", "cron_tick.sh")
QUESTION = "question.json"
ASK = "echo '{\"ask\": \"which branch should the report target?\"}' > question.json"


def tick(d):
    return subprocess.run(["sh", TICK, d], capture_output=True, text=True)


class Waiting(TaskCase):
    def stage(self, run, **kw):
        return {"id": "s", "run": run, "check": "test -s runs.txt", **kw}

    def test_a_stage_that_leaves_a_question_waits_and_is_not_run_again(self):
        d = self.task([self.stage("echo x >> runs.txt; " + ASK)])
        first = mx("run", d)
        self.assertEqual(first.returncode, 7, first.stdout + first.stderr)
        self.assertEqual(self.state(d)["stages"]["s"]["status"], "waiting")
        self.assertEqual(self.state(d)["status"], "waiting")
        self.assertIn("waiting_for_answer", self.events(d))
        self.assertEqual(self.read(d, "runs.txt"), "x\n")
        self.assertNotIn("which branch", self.read(d, "task.json"),
                         "the question text reached the record; it may quote anything")

    def test_a_second_run_while_the_question_stands_costs_nothing_and_writes_nothing(self):
        d = self.task([self.stage("echo x >> runs.txt; " + ASK)])
        mx("run", d)
        before = self.read(d, "journal.jsonl")
        second = mx("run", d)
        self.assertEqual(second.returncode, 7)
        self.assertEqual(self.read(d, "runs.txt"), "x\n", "a waiting stage was run again")
        self.assertEqual(self.read(d, "journal.jsonl"), before, "a tick that learns nothing new wrote a line")

    def test_answering_and_removing_the_file_lets_the_stage_run_again(self):
        d = self.task([self.stage("echo x >> runs.txt; if [ ! -f answered ]; then " + ASK + "; fi")])
        self.assertEqual(mx("run", d).returncode, 7)
        self.write(d, "answered", "")  # the human's answer, wherever the stage reads it
        os.remove(os.path.join(d, QUESTION))
        done = mx("run", d)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.read(d, "runs.txt"), "x\nx\n")
        self.assertEqual(self.state(d)["status"], "complete")
        self.assertIn("question_cleared", self.events(d))

    def test_a_question_file_that_was_already_there_is_not_this_stages_question(self):
        d = self.task([self.stage("echo x >> runs.txt")], {QUESTION: '{"ask": "old"}'})
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.state(d)["stages"]["s"]["status"], "done")

    def test_a_failed_stage_that_leaves_a_question_still_fails(self):
        d = self.task([self.stage("echo x >> runs.txt; " + ASK + "; exit 1")])
        res = mx("run", d)
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertEqual(self.state(d)["stages"]["s"]["status"], "failed",
                         "a question must never hide a failure behind 'waiting'")

    def test_no_later_stage_runs_while_a_question_waits(self):
        d = self.task([self.stage("echo x >> runs.txt; " + ASK),
                       {"id": "next", "run": "echo y > next.txt", "check": "test -s next.txt"}])
        self.assertEqual(mx("run", d).returncode, 7)
        self.assertFalse(os.path.exists(os.path.join(d, "next.txt")), "a later stage ran past a question")

    def test_an_approval_stage_still_needs_a_fresh_approval_after_it_asked(self):
        d = self.task([self.stage("echo x >> runs.txt; " + ASK, deps=["art"], approval="required")], {"art": "A\n"})
        self.assertEqual(mx("run", d).returncode, 4, "an approval stage ran without approval")
        self.assertEqual(mx("approve", d, "s").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 7, "the approved stage did not ask")
        os.remove(os.path.join(d, QUESTION))
        self.assertEqual(mx("run", d).returncode, 4, "the approval was reused for a second execution")
        self.assertEqual(self.read(d, "runs.txt"), "x\n", "the stage ran twice on one approval")

    def test_the_cron_tick_reports_a_waiting_stage_as_needing_a_human(self):
        d = self.task([self.stage("echo x >> runs.txt; " + ASK)])
        res = tick(d)
        self.assertEqual(res.returncode, 7, res.stdout + res.stderr)
        self.assertIn("waiting for an answer", res.stdout)
        self.assertIn(QUESTION, res.stdout)
        self.assertEqual(self.read(d, "runs.txt"), "x\n")


if __name__ == "__main__":
    unittest.main()
