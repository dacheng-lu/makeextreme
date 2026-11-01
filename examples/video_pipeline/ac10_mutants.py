"""AC10 controls: the acceptance must go red when the runner is broken in the way AC10 is about.

Each mutant is applied to a COPY of the repository (never the real tree); the unmutated copy must pass first.
    python ac10_mutants.py --source <file> [--label TEXT]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

MUTANTS = [
    ("M1_finished_stages_are_rerun",
     '            if s.get("digest") == fp:\n                t.log("skip", stage=sid)\n                continue',
     '            if False:\n                t.log("skip", stage=sid)\n                continue',
     "a finished stage is run again on resume"),
    ("M2_orphans_are_not_reaped",
     "            for pg in reap(s):\n                t.log(\"reaped\", stage=sid, pgid=pg)\n        if sp.get(\"approval\") and not (approved(",
     "            for pg in []:\n                t.log(\"reaped\", stage=sid, pgid=pg)\n        if sp.get(\"approval\") and not (approved(",
     "the killed OCR loop keeps running beside its replacement"),
    ("M3_crash_not_recognised",
     'if s["status"] in ("running", "interrupted"):  # the previous runner died or was stopped mid-stage',
     'if False:  # the previous runner died or was stopped mid-stage',
     "a stage left `running` by a killed runner is not recognised"),
]


def run_ac10(repo, args):
    r = subprocess.run([sys.executable, os.path.join(repo, "examples/video_pipeline/ac10.py"), "--source", args.source,
                        "--label", args.label or args.source, "--work", os.path.join(repo, "_ac10work")],
                       capture_output=True, text=True, timeout=280)
    fails = [l for l in r.stdout.splitlines() if l.startswith("FAIL")]
    return r.returncode, fails, r.stdout[-300:] + r.stderr[-300:]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--label")
    a = ap.parse_args(argv)
    ok = True
    with tempfile.TemporaryDirectory(dir=os.path.expanduser("~/ac10work")) as tmp:
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        base = os.path.join(tmp, "control")
        shutil.copytree(REPO, base, ignore=ignore)
        rc, fails, tail = run_ac10(base, a)
        print("CONTROL (unmutated copy): rc=%d %s" % (rc, "green" if rc == 0 else "RED  " + tail))
        ok &= rc == 0
        for name, old, new, what in MUTANTS:
            copy = os.path.join(tmp, name)
            shutil.copytree(REPO, copy, ignore=ignore)
            p = os.path.join(copy, "makeextreme", "core.py")
            src = open(p).read()
            if src.count(old) != 1:
                print("%s: SUBSTITUTION FAILED (%d matches)" % (name, src.count(old)))
                ok = False
                continue
            open(p, "w").write(src.replace(old, new))
            rc, fails, tail = run_ac10(copy, a)
            print("%s: rc=%d %s | %s\n    first red: %s" % (name, rc, "RED (good)" if rc else "STILL GREEN (bad)", what,
                                                         (fails[0][:150] if fails else tail[-150:])))
            ok &= rc != 0
    print("\nCONTROLS %s" % ("OK: green control, every mutant red" if ok else "NOT OK"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
