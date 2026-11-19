"""Primary-source check: figures need citations; citations need an independent, confirmed check."""
import json, os, subprocess, sys, tempfile, unittest

from support import REPO

from makeextreme.source_check import problems

GOOD = {"author": "writer", "sources": {"1": {"url": "https://example.org/r", "locator": "p. 4",
                                              "checked_by": "auditor", "verdict": "confirmed"}}}


def src(**over):
    d = json.loads(json.dumps(GOOD))
    d["sources"]["1"].update(over)
    return d


class SourceCheck(unittest.TestCase):
    def test_cited_and_independently_confirmed_passes(self):
        self.assertEqual(problems("# Title 2026\nRevenue grew 12 % [1].\nPlain prose.", GOOD), [])

    def test_figure_without_citation_fails(self):
        self.assertEqual(problems("Revenue grew 12 %.", GOOD), ["line 1: figure or quote without citation"])

    def test_quote_without_citation_fails(self):
        self.assertTrue(problems('He said "we ship weekly".', GOOD))

    def test_unknown_marker_fails(self):
        self.assertIn("[2]: no such source", problems("x 5 [2]", GOOD))

    def test_author_cannot_check_own_source(self):
        self.assertIn("[1]: checked by the author", problems("x 5 [1]", src(checked_by="writer")))

    def test_unchecked_or_unconfirmed_fails(self):
        self.assertIn("[1]: not checked", problems("x 5 [1]", src(checked_by="")))
        self.assertTrue(any("verdict" in p for p in problems("x 5 [1]", src(verdict="disputed"))))

    def test_missing_locator_fails(self):
        self.assertIn("[1]: missing locator", problems("x 5 [1]", src(locator="")))

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            r, s = os.path.join(d, "r.md"), os.path.join(d, "s.json")
            with open(s, "w", encoding="utf-8") as f:
                json.dump(GOOD, f)
            for text, code in (("ok 5 [1]\n", 0), ("bad 5\n", 1)):
                with open(r, "w", encoding="utf-8") as f:
                    f.write(text)
                res = subprocess.run([sys.executable, "-m", "makeextreme.source_check", r, s],
                                     cwd=REPO, capture_output=True, text=True)
                self.assertEqual(res.returncode, code, res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
