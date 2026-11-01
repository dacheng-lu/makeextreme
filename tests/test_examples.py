"""Small facts about the examples that no acceptance run covers because those need ffmpeg, whisper or a network."""
import os, subprocess, sys, tempfile, unittest

from support import REPO


class Ac10MutantsOnAFreshMachine(unittest.TestCase):
    def test_the_mutant_harness_creates_its_work_directory_instead_of_crashing(self):
        """Found by the D19 audit: ~/ac10work only existed if ac10.py had been run before, so the documented evidence command died
        with FileNotFoundError before it did anything on a fresh machine."""
        with tempfile.TemporaryDirectory(prefix="home-") as home:
            res = subprocess.run([sys.executable, os.path.join(REPO, "examples", "video_pipeline", "ac10_mutants.py"),
                                  "--source", os.path.join(home, "no-such.mp4")],
                                 env=dict(os.environ, HOME=home), capture_output=True, text=True, timeout=250)
            self.assertNotIn("FileNotFoundError", res.stderr, res.stderr[-400:])
            self.assertTrue(os.path.isdir(os.path.join(home, "ac10work")))
            self.assertIn("CONTROL", res.stdout)  # it got as far as the control run (which is red here: the source does not exist)


if __name__ == "__main__":
    unittest.main()
