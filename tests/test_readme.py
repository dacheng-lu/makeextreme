"""The three READMEs state the same measured facts (decision D16). Standard library only.

Every language must carry the same required facts, the numbers it quotes must equal what the repository really has,
and none may make a comparative claim (decision D8: only measured facts are published).
"""
import os
import re
import subprocess
import sys
import unittest

from support import REPO

sys.path.insert(0, REPO)
from makeextreme import __version__, core  # noqa: E402

LANGS = {
    "README.md": {"tests": r"\b{n} tests\b", "mutants": r"\b{m} mutants\b",
                  "forbidden": ["better than", "faster than", "superior", "best-in-class", "state of the art", "outperform"]},
    "README.zh.md": {"tests": r"{n} 个测试", "mutants": r"{m} 个变异体",
                     "forbidden": ["优于", "胜过", "最好的", "最佳", "领先于", "碾压"]},
    "README.de.md": {"tests": r"\b{n} Tests\b", "mutants": r"\b{m} Mutanten\b",
                     "forbidden": ["besser als", "schneller als", "überlegen", "bestes", "übertrifft"]},
}
COMMANDS = ["python -m makeextreme run <task_dir>",
            "python -m makeextreme approve <task_dir> <stage>",
            "python -m makeextreme resolve <task_dir> <stage>"]
FACTS = ["Apache-2.0", "3.11", "3.14", "Linux", "AC10", "AC9", "kill -9", "examples/cron_tick.sh", "stages.json",
         "approval", "SOURCES.md", "NOTICE.md", "ARCHITECTURE.md", "LICENSE", "env -i", "setsid", "SIGTERM",
         "task.json", "journal.jsonl", "2026-11-01", "Sonnet 5.5", "areeves/revenant", "dacheng-lu/longhaul"]


def read(name):
    with open(os.path.join(REPO, name), encoding="utf-8") as f:
        return f.read()


def real_counts():
    # a fresh loader: `unittest -k <pattern>` sets its name filter on the shared defaultTestLoader and would shrink the count
    tests = unittest.TestLoader().discover(os.path.join(REPO, "tests"), pattern="test_*.py").countTestCases()
    listed = subprocess.run([sys.executable, os.path.join(REPO, "tests", "mutants.py"), "list"], capture_output=True,
                            text=True, check=True).stdout.split("\n")
    return tests, len([line for line in listed if line.strip()])


class ReadmeFacts(unittest.TestCase):
    def test_the_numbers_quoted_are_the_numbers_the_repository_has(self):
        n, m = real_counts()
        for name, spec in LANGS.items():
            text = read(name)
            for key, count in (("tests", n), ("mutants", m)):
                self.assertRegex(text, spec[key].format(n=count, m=count), "%s: %s should be %d" % (name, key, count))

    def test_every_language_carries_the_same_required_facts(self):
        for name in LANGS:
            text = read(name)
            for token in COMMANDS + FACTS:
                self.assertIn(token, text, "%s lacks %r" % (name, token))
            self.assertIn(__version__, text, "%s lacks the version %s" % (name, __version__))

    def test_every_exit_code_of_the_runner_is_listed_in_every_language(self):
        codes = {0, core.EX_FAILED, core.EX_LOCKED, core.EX_AWAITING, core.EX_UNCERTAIN, core.EX_SECRET, core.EX_SPEC}
        for name in LANGS:
            text = read(name)
            for code in codes:
                self.assertIn("`%d`" % code, text, "%s does not list exit code %d" % (name, code))

    def test_no_language_makes_a_comparative_claim(self):
        for name, spec in LANGS.items():
            text = read(name).lower()
            for word in spec["forbidden"]:
                self.assertNotIn(word.lower(), text, "%s contains the comparative claim %r" % (name, word))

    def test_each_readme_points_to_the_other_two(self):
        links = {"README.md": ("README.zh.md", "README.de.md"), "README.zh.md": ("README.md", "README.de.md"),
                 "README.de.md": ("README.md", "README.zh.md")}
        for name, others in links.items():
            for other in others:
                self.assertIn("(%s)" % other, read(name), "%s does not link to %s" % (name, other))
                self.assertTrue(os.path.exists(os.path.join(REPO, other)))


if __name__ == "__main__":
    unittest.main()
