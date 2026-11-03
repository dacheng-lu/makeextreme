"""README.md states the same measured facts in three languages (decisions D16, D8). Standard library only.

The page is one file with a section per language, like the Longhaul README. Every language section must carry the
same required facts and the same subsections, the numbers it quotes must equal what the repository really has, no
section may make a comparative claim, and the logo and every relative link must point at a real file.
"""
import os
import re
import struct
import subprocess
import sys
import unittest

from support import REPO

sys.path.insert(0, REPO)
from makeextreme import __version__, core  # noqa: E402

LANGS = {
    "English": {"anchor": "#english", "version": "Version {v}, one author", "tests": r"\b{n} tests\b", "mutants": r"\b{m} mutants\b",
                "forbidden": ["better than", "faster than", "superior", "best-in-class", "state of the art", "outperform"]},
    "简体中文": {"anchor": "#zh-cn", "version": "版本 {v}，单人开发", "tests": r"{n} 个测试", "mutants": r"{m} 个变异体",
                 "forbidden": ["优于", "胜过", "最好的", "最佳", "领先于", "碾压"]},
    "Deutsch": {"anchor": "#deutsch", "version": "Version {v}, ein Autor", "tests": r"\b{n} Tests\b", "mutants": r"\b{m} Mutanten\b",
                "forbidden": ["besser als", "schneller als", "überlegen", "bestes", "übertrifft"]},
}
COMMANDS = ["python -m makeextreme run <task_dir>",
            "python -m makeextreme approve <task_dir> <stage>",
            "python -m makeextreme resolve <task_dir> <stage>"]
# facts every language section states in its own words (identifiers stay in Latin letters)
PROSE_FACTS = ["3.11", "3.14", "Linux", "AC10", "AC9", "kill -9", "examples/cron_tick.sh", "stages.json", "approval",
               "env -i", "setsid", "SIGTERM", "task.json", "journal.jsonl", "2026-11-01", "Longhaul"]
# facts the shared tail of the page states once
PAGE_FACTS = ["Apache-2.0", "LICENSE", "SOURCES.md", "NOTICE.md", "ARCHITECTURE.md", "areeves/revenant",
              "dacheng-lu/longhaul", "assets/logo.jpg", "assets/social-preview.png"]
LOGO, SOCIAL = "assets/logo.jpg", "assets/social-preview.png"
HEADER_LOGO = "assets/logo-readme.svg"  # what the header shows since pull request #1 (2026-11-02); logo.jpg stays the listed original


def page():
    with open(os.path.join(REPO, "README.md"), encoding="utf-8") as f:
        return f.read()


def sections():
    """heading -> body, for every `## ` heading (a `### ` line belongs to the section above it)."""
    out, name, buf = {}, "preamble", []
    for line in page().split("\n"):
        if line.startswith("## "):
            out[name] = "\n".join(buf)
            name, buf = line[3:].strip(), []
        else:
            buf.append(line)
    out[name] = "\n".join(buf)
    return out


def real_counts():
    # a fresh loader: `unittest -k <pattern>` sets its name filter on the shared defaultTestLoader and would shrink the count
    tests = unittest.TestLoader().discover(os.path.join(REPO, "tests"), pattern="test_*.py").countTestCases()
    listed = subprocess.run([sys.executable, os.path.join(REPO, "tests", "mutants.py"), "list"], capture_output=True,
                            text=True, check=True).stdout.split("\n")
    return tests, len([line for line in listed if line.strip()])


class ReadmeFacts(unittest.TestCase):
    def test_the_page_has_one_section_per_language_and_the_shared_tail(self):
        have = sections()
        for name in list(LANGS) + ["Files and design references"]:
            self.assertIn(name, have, "the page has no '## %s' section" % name)

    def test_the_numbers_quoted_are_the_numbers_the_repository_has(self):
        n, m = real_counts()
        have = sections()
        for name, spec in LANGS.items():
            for key, count in (("tests", n), ("mutants", m)):
                self.assertRegex(have[name], spec[key].format(n=count, m=count), "%s: %s should be %d" % (name, key, count))

    def test_every_language_carries_the_same_required_facts(self):
        have = sections()
        for name in LANGS:
            for token in COMMANDS + PROSE_FACTS:
                self.assertIn(token, have[name], "the %s section lacks %r" % (name, token))
            # the statement itself, not any mention: a feature note that says "(1.1.0)" must not satisfy this
            self.assertIn(LANGS[name]["version"].format(v=__version__), have[name],
                          "the %s section does not state version %s" % (name, __version__))
        self.assertIn("Version: **%s** ·" % __version__, have["preamble"], "the page header does not state the version")
        for token in PAGE_FACTS:
            self.assertIn(token, page(), "the page lacks %r" % token)

    def test_every_language_says_that_this_release_refuses_a_task_the_previous_one_accepted(self):
        """The owner chose 1.2.0 over 1.1.1 (2026-11-02) because two stages declaring the same output ran under 1.1.0 and exit 64 now:
        a patch number must not hide a tightening, and the page must say so in every language."""
        have = sections()
        says = {"English": ("since 1.2.0", "1.1.0 accepted such a task"), "简体中文": ("自 1.2.0 起", "1.1.0 接受这样的任务"),
                "Deutsch": ("seit 1.2.0", "1.1.0 akzeptierte eine solche Aufgabe")}
        for name, tokens in says.items():
            for token in tokens:
                self.assertIn(token, have[name], "the %s section does not say %r" % (name, token))

    def test_every_exit_code_of_the_runner_is_listed_in_every_language(self):
        codes = {0, core.EX_FAILED, core.EX_LOCKED, core.EX_AWAITING, core.EX_UNCERTAIN, core.EX_SECRET, core.EX_SPEC,
                 core.EX_WAITING}
        have = sections()
        for name in LANGS:
            for code in codes:
                self.assertIn("`%d`" % code, have[name], "the %s section does not list exit code %d" % (name, code))

    def test_exit_code_64_names_every_cause_in_every_language(self):
        """Found by the D19 audit: 64 is also returned for a damaged task.json and for a declared output that cannot be read."""
        have = sections()
        for name in LANGS:
            line = next((l for l in have[name].split("\n") if "`64`" in l and "`6`" in l), None)
            self.assertIsNotNone(line, "the %s section has no exit-code line" % name)
            self.assertIn("task.json", line, "the %s exit-code line does not say that 64 also covers a damaged task.json" % name)
            self.assertRegex(line.split("`64`", 1)[1], r"(?i)output|产物|Ausgabe", "the %s exit-code line leaves out the unreadable output" % name)

    def test_the_command_that_runs_the_ac10_mutants_carries_its_required_argument_in_every_language(self):
        """The script needs --source; the documented command used to be rejected without it."""
        have = sections()
        for name in LANGS:
            hits = re.findall(r"python examples/video_pipeline/ac10_mutants\.py[^`]*", have[name])
            self.assertTrue(hits, "the %s section does not give the AC10 mutant command" % name)
            for h in hits:
                self.assertIn("--source", h, "the %s section gives %r without --source" % (name, h))

    def test_no_language_makes_a_comparative_claim(self):
        text = page().lower()
        for name, spec in LANGS.items():
            for word in spec["forbidden"]:
                self.assertNotIn(word.lower(), text, "the page contains the comparative claim %r (%s)" % (word, name))

    def test_navigation_and_structure_are_the_same_in_every_language(self):
        have, text = sections(), page()
        for name, spec in LANGS.items():
            self.assertIn("(%s)" % spec["anchor"], have["preamble"], "the language bar does not link to %s" % name)
        self.assertIn('<a name="zh-cn"></a>', text, "the Chinese section has no explicit anchor")
        counts = {name: have[name].count("\n### ") + (1 if have[name].startswith("### ") else 0) for name in LANGS}
        self.assertEqual(len(set(counts.values())), 1, "the languages have different subsections: %r" % counts)
        self.assertEqual(text.count("(#files-and-design-references)"), 3, "each language should link to the shared tail")

    def test_the_logo_and_the_social_preview_are_real_images_the_page_uses(self):
        self.assertRegex(page(), r'<img src="%s"[^>]*width="\d+"' % re.escape(HEADER_LOGO), "the header does not show the logo")
        with open(os.path.join(REPO, HEADER_LOGO), "rb") as f:
            header = f.read()
        self.assertTrue(header.lstrip().startswith(b"<svg"), "the header logo is not an SVG")
        self.assertIn(b"<title", header, "the header logo has no title for screen readers")
        self.assertGreater(len(header), 10_000, "the header logo is too small to be the picture")
        with open(os.path.join(REPO, LOGO), "rb") as f:
            logo = f.read()
        self.assertEqual(logo[:3], b"\xff\xd8\xff", "the original logo is not a JPEG")
        self.assertGreater(len(logo), 10_000)
        with open(os.path.join(REPO, SOCIAL), "rb") as f:
            png = f.read(33)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n", "the social preview is not a PNG")
        self.assertEqual(struct.unpack(">II", png[16:24]), (1280, 640), "GitHub wants 1280x640 for the social preview")

    def test_every_relative_link_and_image_in_the_page_points_at_a_file_that_exists(self):
        targets = re.findall(r'\]\(([^)#\s]+)(?:#[^)]*)?\)', page()) + re.findall(r'src="([^"]+)"', page())
        targets = [t for t in targets if "://" not in t]
        self.assertGreater(len(targets), 10)
        for target in targets:
            self.assertTrue(os.path.exists(os.path.join(REPO, target)), "the page links to %s, which does not exist" % target)


if __name__ == "__main__":
    unittest.main()
