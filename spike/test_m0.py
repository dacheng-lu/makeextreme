#!/usr/bin/env python3
"""M0 acceptance probes. Each prints PASS/FAIL with the observed numbers. No network, no model."""
import hashlib, json, os, signal, subprocess, sys, tempfile, time

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner.py")
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


def task(stages):
    d = tempfile.mkdtemp(prefix="m0-")
    json.dump(stages, open(os.path.join(d, "stages.json"), "w"))
    return d


def go(d, **kw):
    return subprocess.run([sys.executable, RUNNER, "run", d], capture_output=True, text=True, **kw)


def start(d):
    return subprocess.Popen([sys.executable, RUNNER, "run", d])


def lines(d, name):
    p = os.path.join(d, name)
    return len(open(p).read().splitlines()) if os.path.exists(p) else 0


def wait_for(path, secs=6):
    end = time.time() + secs
    while time.time() < end:
        if os.path.exists(path):
            return True
        time.sleep(0.05)
    return False


def state(d):
    return json.load(open(os.path.join(d, "task.json")))


def events(d):
    return [json.loads(x)["ev"] for x in open(os.path.join(d, "journal.jsonl"))]


def sha(d):
    return hashlib.sha256(open(os.path.join(d, "task.json"), "rb").read()).hexdigest()


S3 = [
    {"id": "s1", "run": "echo x >> c1", "check": "test -s c1"},
    {"id": "s2", "run": "echo y >> c2; sleep 4; echo done >> s2.done", "check": "test -s s2.done"},
    {"id": "s3", "run": "echo z >> c3", "check": "test -s c3"},
]

# AC1: kill -9 the runner mid-stage; the stage's orphan must be reaped, finished stages not redone
d = task(S3)
r = start(d)
assert wait_for(os.path.join(d, "c2")), "stage 2 never started"
pgid = state(d)["stages"]["s2"]["pgid"]
os.kill(r.pid, signal.SIGKILL)
r.wait()
try:
    os.killpg(pgid, 0)
    orphan_alive = True
except ProcessLookupError:
    orphan_alive = False
check("AC1a runner SIGKILLed mid-stage leaves a live orphan (the hazard is real)", orphan_alive)
t0 = time.time()
res = go(d)
st = state(d)
check("AC1b resume completes", res.returncode == 0 and st["status"] == "complete", f"rc={res.returncode} {time.time()-t0:.1f}s")
check("AC1c finished stage not re-run, crashed stage re-run once, later stage run once",
      (lines(d, "c1"), lines(d, "c2"), lines(d, "c3")) == (1, 2, 1), f"c1/c2/c3={lines(d,'c1')}/{lines(d,'c2')}/{lines(d,'c3')}")
check("AC1d orphan was reaped (only the re-run wrote the done marker)", lines(d, "s2.done") == 1, f"s2.done lines={lines(d,'s2.done')}")
check("AC1e journal records crash recovery and reaping", {"recovered_from_crash", "reaped"} <= set(events(d)))

# AC3: resume of a completed task executes nothing and leaves state byte-identical
before = sha(d)
res = go(d)
check("AC3 idempotent: no stage re-run, state byte-identical",
      res.returncode == 0 and sha(d) == before and (lines(d, "c1"), lines(d, "c2"), lines(d, "c3")) == (1, 2, 1))

# AC2: exit 0 with a failing check is not "done"; later stages must not run
d2 = task([{"id": "a", "run": "echo hi", "check": "false"}, {"id": "b", "run": "touch b.ran", "check": "true"}])
res = go(d2)
st = state(d2)
check("AC2 exit 0 + failing exit-check => failed, runner stops, next stage untouched",
      res.returncode == 2 and st["stages"]["a"]["status"] == "failed" and not os.path.exists(os.path.join(d2, "b.ran"))
      and "b" not in st["stages"], f"rc={res.returncode} a={st['stages']['a']['status']}")

# AC7: SIGTERM (the cron -15 case) is journaled as interrupted and resumable
d3 = task([{"id": "s", "run": "echo go >> c; sleep 3; echo done >> d", "check": "test -s d"}])
r = start(d3)
assert wait_for(os.path.join(d3, "c")), "stage never started"
r.send_signal(signal.SIGTERM)
rc = r.wait()
st = state(d3)
check("AC7a SIGTERM => exit 143, state+journal say interrupted",
      rc == 143 and st["status"] == "interrupted" and "interrupted" in events(d3), f"rc={rc}")
res = go(d3)
check("AC7b resume after SIGTERM completes, interrupted run never wrote its marker",
      res.returncode == 0 and lines(d3, "c") == 2 and lines(d3, "d") == 1, f"c={lines(d3,'c')} d={lines(d3,'d')}")

# AC4: live lock refuses; dead lock is taken over
d4 = task([{"id": "s", "run": "echo ok >> c", "check": "test -s c"}])
me = {"pid": os.getpid(), "start": open(f"/proc/{os.getpid()}/stat").read().rsplit(")", 1)[1].split()[19]}
json.dump(me, open(os.path.join(d4, "lock"), "w"))
res = go(d4)
check("AC4a live lock holder => refuse (exit 3), nothing ran", res.returncode == 3 and lines(d4, "c") == 0, res.stderr.strip())
dead = subprocess.Popen(["true"])
dead.wait()
json.dump({"pid": dead.pid, "start": "1"}, open(os.path.join(d4, "lock"), "w"))
res = go(d4)
check("AC4b dead lock holder => taken over, task completes", res.returncode == 0 and lines(d4, "c") == 1)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
