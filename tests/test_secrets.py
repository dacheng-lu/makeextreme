"""AC8: completion is refused while task.json or the journal holds a secret-shaped value."""
import json, os, unittest

from support import TaskCase, mx

KEY = "sk-" + "a1B2c3D4" * 4  # provider-shaped, assembled here so no key-like literal sits in the source


def leaky():
    return [{"id": "s", "run": "echo ok > ok", "check": f"printf '%s' {KEY}; test -s ok"}]


class Secrets(TaskCase):
    def test_a_credential_in_the_state_refuses_completion_and_the_value_is_not_echoed(self):
        d = self.task(leaky())
        res = mx("run", d)
        self.assertEqual(res.returncode, 6, res.stderr)
        self.assertNotIn(KEY, res.stdout + res.stderr)
        st = self.state(d)
        self.assertEqual(st["status"], "refused_secret")
        self.assertEqual([(h["file"], h["kind"]) for h in st["secret_hits"]], [("task.json", "provider_key")])
        self.assertNotIn(KEY, json.dumps(st["secret_hits"]))
        self.assertIn("refused_secret", self.events(d))

    def test_a_credential_in_the_journal_refuses_a_rerun_until_the_line_is_removed(self):
        d = self.task([{"id": "s", "run": "echo ok > ok", "check": "test -s ok"}])
        self.assertEqual(mx("run", d).returncode, 0)
        with open(os.path.join(d, "journal.jsonl"), "a") as f:
            f.write(json.dumps({"ev": "note", "msg": f"api_key={KEY}"}) + "\n")
        res = mx("run", d)
        self.assertEqual(res.returncode, 6)
        self.assertIn("journal.jsonl", res.stderr)
        self.assertNotIn(KEY, res.stdout + res.stderr)
        kept = [x for x in self.read(d, "journal.jsonl").splitlines() if KEY not in x and "refused_secret" not in x]
        self.write(d, "journal.jsonl", "\n".join(kept) + "\n")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertNotIn("secret_hits", self.state(d))

    def test_a_torn_journal_line_is_scanned_as_text_not_skipped(self):
        d = self.task([{"id": "s", "run": "echo ok > ok", "check": "test -s ok"}])
        mx("run", d)
        with open(os.path.join(d, "journal.jsonl"), "a") as f:
            f.write('{"ev": "note", "msg": "token ' + KEY)  # no closing: a write cut short by a crash
        self.assertEqual(mx("run", d).returncode, 6)

    def test_digests_and_approvals_are_not_mistaken_for_secrets(self):
        spec = [{"id": "make", "run": "echo report > artifact.txt", "check": "test -s artifact.txt"},
                {"id": "send", "run": "echo sent > rs", "check": "test -s rs", "deps": ["artifact.txt"],
                 "approval": "required"}]
        d = self.task(spec)
        mx("run", d)
        mx("approve", d, "send")
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr)  # 64-hex digests sit in task.json and approvals.jsonl
        self.assertEqual(self.state(d)["status"], "complete")


if __name__ == "__main__":
    unittest.main()
