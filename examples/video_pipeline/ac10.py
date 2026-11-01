"""AC10: the video pipeline survives `kill -9` during OCR and ends with the same bytes as an uninterrupted run.

    python ac10.py --source <url-or-file> [--label TEXT] [--work DIR] [--kill-after N]

On demand, not in CI (needs ffmpeg, yt-dlp for a URL, tesseract with chi_sim, a cached Whisper model).

U: uninterrupted run (fetches `--source`: a real download when it is a URL).
K: the same video (copied from U's src.mp4, so both start from identical bytes), runner killed with SIGKILL while
   the OCR stage is running, then run again.
Passes only when every artifact of K equals U's, the journal shows that no finished stage ran twice, and no
process of either task is left alive. The transcript is the one thing that is not bit-deterministic (see
bin/asr.py); both runs read it from the cache keyed by the audio's hash, so this test proves resumption, not
Whisper determinism.
"""
import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ARTIFACTS = ["src.mp4", "audio.wav", "asr.txt", "frames", "ocr", "brief.md", "deliver/brief.md"]
STAGES = ["fetch", "audio", "asr", "frames", "ocr", "assemble", "deliver"]


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_path(p):
    if not os.path.exists(p):
        return "missing"
    if os.path.isfile(p):
        return sha_file(p)
    h = hashlib.sha256()
    for name in sorted(os.listdir(p)):
        h.update(name.encode() + b"\0" + sha_path(os.path.join(p, name)).encode() + b"\n")
    return h.hexdigest()


def mx(*args, **kw):
    return subprocess.run([sys.executable, "-m", "makeextreme", *args], cwd=REPO, capture_output=True,
                          text=True, **kw)


def journal(d):
    with open(os.path.join(d, "journal.jsonl")) as f:
        return [json.loads(line) for line in f if line.strip()]


def alive_in(d):
    """pids whose working directory is inside `d` (orphans of a killed stage)."""
    out = []
    for pid in os.listdir("/proc"):
        if pid.isdigit() and int(pid) != os.getpid():
            try:
                cwd = os.readlink("/proc/%s/cwd" % pid)
            except OSError:
                continue
            if cwd == d or cwd.startswith(d + os.sep):
                out.append(int(pid))
    return out


def new_task(d, source, label):
    r = subprocess.run([sys.executable, os.path.join(HERE, "new_task.py"), d, source, "--label", label],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit("new_task failed: " + r.stderr)


def finish(d, results, name):
    """run -> waits for approval (4) -> approve -> run -> done (0)."""
    r = mx("run", d)
    results.append((name + ": run reaches the approval gate (exit 4)", r.returncode == 4, "exit %d" % r.returncode))
    a = mx("approve", d, "deliver")
    results.append((name + ": approve", a.returncode == 0, "exit %d" % a.returncode))
    r = mx("run", d)
    results.append((name + ": run completes (exit 0)", r.returncode == 0, "exit %d %s" % (r.returncode, r.stderr[-120:])))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--label")
    ap.add_argument("--work", default=os.path.expanduser("~/ac10work/run"))
    ap.add_argument("--kill-after", type=int, default=4, help="kill once this many frames are OCRed")
    a = ap.parse_args(argv)
    label = a.label or a.source
    shutil.rmtree(a.work, ignore_errors=True)
    U, K = os.path.join(a.work, "U"), os.path.join(a.work, "K")
    os.makedirs(a.work)
    results = []

    t0 = time.time()
    new_task(U, a.source, label)
    finish(U, results, "U")
    t_u = time.time() - t0

    new_task(K, os.path.join(U, "src.mp4"), label)  # the same bytes, copied; the label stays the original
    run = subprocess.Popen([sys.executable, "-m", "makeextreme", "run", K], cwd=REPO,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    part = os.path.join(K, "ocr.part")
    deadline = time.time() + 600
    n = 0
    while time.time() < deadline and run.poll() is None:
        n = len(os.listdir(part)) if os.path.isdir(part) else 0
        if n >= a.kill_after:
            break
        time.sleep(0.02)
    if run.poll() is not None or n < a.kill_after:
        sys.exit("the runner ended before the kill window (frames OCRed: %d)" % n)
    os.kill(run.pid, signal.SIGKILL)
    run.wait()
    with open(os.path.join(K, "task.json")) as f:
        at_kill = json.load(f)["stages"]
    results.append(("K: killed during OCR (ocr running, no finished ocr dir)",
                    at_kill["ocr"]["status"] == "running" and not os.path.exists(os.path.join(K, "ocr")),
                    "ocr.part had %d files, ocr status %s" % (n, at_kill["ocr"]["status"])))
    orphans = alive_in(K)
    finish(K, results, "K")

    ev = journal(K)
    starts = {s: sum(1 for e in ev if e["ev"] == "start" and e["stage"] == s) for s in STAGES}
    want = {s: 1 for s in STAGES}
    want["ocr"] = 2
    results.append(("K: no finished stage ran twice (starts per stage)", starts == want, json.dumps(starts)))
    results.append(("K: the crash was recognised for ocr",
                    any(e["ev"] == "recovered_from_crash" and e["stage"] == "ocr" for e in ev), ""))
    results.append(("K: no orphan of the killed OCR left after the resume",
                    not [p for p in orphans if os.path.exists("/proc/%d" % p)] and not alive_in(K),
                    "orphans right after the kill: %d" % len(orphans)))
    results.append(("U: every stage ran exactly once",
                    {s: sum(1 for e in journal(U) if e["ev"] == "start" and e["stage"] == s) for s in STAGES} == want | {"ocr": 1},
                    ""))
    for art in ARTIFACTS:
        hu, hk = sha_path(os.path.join(U, art)), sha_path(os.path.join(K, art))
        results.append(("artifact %s: K equals U" % art, hu == hk and hu != "missing", "%s %s" % (hu[:12], hk[:12])))

    width = max(len(r[0]) for r in results)
    for name, ok, note in results:
        print("%s  %-*s  %s" % ("PASS" if ok else "FAIL", width, name, note))
    ok = all(r[1] for r in results)
    final = sha_path(os.path.join(K, "deliver/brief.md"))
    print("\nAC10 %s: final artifact sha256 %s (U took %.0f s)" % ("PASS" if ok else "FAIL", final[:16], t_u))
    with open(os.path.join(a.work, "ac10_result.json"), "w") as f:
        json.dump({"pass": ok, "final_sha256": final, "results": [list(r) for r in results]}, f, indent=2)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
