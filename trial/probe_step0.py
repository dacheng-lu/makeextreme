#!/usr/bin/env python3
"""Step-0 trial harness: one scenario set, run against interchangeable adapters (black-box, tool under test is never edited).
Adapters:  toolkit = chenhz01/resilient-agent-toolkit-v2 @ad767d0 01_durable_steps.py   |   spike = our M0 runner (control)
Usage: probe_step0.py toolkit|spike
Abstract step: {"id", "argv": [...], "check": [...]|None, "gate": bool}
"""
import json, os, shlex, signal, subprocess, sys, tempfile, time, hashlib

PY = sys.executable
TOOLKIT = os.path.expanduser("~/study/sources/step0/resilient-agent-toolkit-v2/01_durable_steps.py")
SPIKE = os.path.expanduser("~/Projects/makeextreme/spike/runner.py")
WHICH = sys.argv[1]
res = []


def rec(name, ok, detail=""):
    res.append((name, ok, detail)); print(("PASS" if ok else ("N/A " if ok is None else "FAIL")), name, "|", detail, flush=True)


def alive(pid):
    try:
        os.kill(pid, 0)
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except Exception:
        return False


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


class Adapter:
    def __init__(self, tmp, steps):
        self.tmp = tmp
        if WHICH == "toolkit":
            spec = []
            for s in steps:
                if s.get("gate"):
                    spec.append({"id": s["id"], "gate": True, "note": "needs human"})
                else:  # toolkit has NO check concept: s["check"] is dropped (native behaviour)
                    spec.append({"id": s["id"], "cmd": s["argv"], "critical": True})
            self.spec = os.path.join(tmp, "spec.json"); json.dump(spec, open(self.spec, "w"))
            self.state = os.path.join(tmp, "ck.json")
            self.cmd = [PY, TOOLKIT, "run", self.spec, self.state]
        else:
            spec = []
            for s in steps:
                if s.get("gate"):
                    spec.append(None); continue
                spec.append({"id": s["id"], "run": shlex.join(s["argv"]), "check": shlex.join(s["check"]) if s.get("check") else "true"})
            self.has_gate = all(x is not None for x in spec)
            spec = [x for x in spec if x]
            json.dump(spec, open(os.path.join(tmp, "stages.json"), "w"))
            self.state = os.path.join(tmp, "task.json")
            self.cmd = [PY, SPIKE, "run", tmp]

    def start(self):
        return subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def run(self, timeout=40):
        p = self.start(); p.wait(timeout=timeout); return p.returncode

    def status(self):
        try:
            return json.load(open(self.state)).get("status")
        except Exception:
            return None

    def mentions_interrupt(self):
        for root, _, fs in os.walk(self.tmp):
            for f in fs:
                if f.endswith((".json", ".jsonl")) and "interrupt" in open(os.path.join(root, f), errors="ignore").read().lower():
                    return True
        return False


def argv_count(tmp, name, body=""):
    code = f"open({os.path.join(tmp, name + '.runs')!r},'a').write('x\\n');{body}"
    return [PY, "-c", code]


def runs(tmp, name):
    p = os.path.join(tmp, name + ".runs")
    return len(open(p).read().split()) if os.path.exists(p) else 0


# ---------- AC1: kill -9 the runner mid-stage ----------
with tempfile.TemporaryDirectory() as tmp:
    pidf = os.path.join(tmp, "B.pid")
    a = Adapter(tmp, [
        {"id": "A", "argv": argv_count(tmp, "A")},
        # first execution (runs file has 1 line) lingers 60 s; a re-execution returns at once.
        # => if the first one is still alive after resume, it was NOT reaped (not merely finished by itself).
        {"id": "B", "argv": argv_count(tmp, "B", f"import os,time;open({pidf!r},'w').write(str(os.getpid()));n=len(open({os.path.join(tmp,'B.runs')!r}).read().split());time.sleep(60 if n==1 else 0)")},
        {"id": "C", "argv": argv_count(tmp, "C")}])
    p = a.start()
    for _ in range(100):
        if os.path.exists(pidf) and open(pidf).read().strip(): break
        time.sleep(0.1)
    child = int(open(pidf).read())
    p.kill(); p.wait(); time.sleep(0.3)
    # (not asserted: nobody can reap at the moment of kill -9; AC1 is defined AFTER resume)
    a.run()
    gone = not alive(child)
    rec("AC1a after resume, the killed run's child process is gone (reaped, not self-finished)", gone, f"child {child} alive_after_resume={not gone}")
    if not gone: os.kill(child, signal.SIGKILL)
    rec("AC1b completed stage A is not re-run", runs(tmp, "A") == 1, f"A ran {runs(tmp,'A')}x")
    rec("AC1c crashed stage B ran exactly 2x (1 killed + 1 resume)", runs(tmp, "B") == 2, f"B ran {runs(tmp,'B')}x")
    rec("AC1d pipeline completes after resume", a.status() in ("done", "complete"), f"status={a.status()}")

# ---------- AC2: exit 0 but artifact wrong ----------
with tempfile.TemporaryDirectory() as tmp:
    out = os.path.join(tmp, "out.txt")
    a = Adapter(tmp, [
        {"id": "produce", "argv": [PY, "-c", f"open({out!r},'w').write('PARTIAL 159/272')"], "check": ["grep", "-q", "272/272", out]},
        {"id": "after", "argv": argv_count(tmp, "after")}])
    a.run()
    rec("AC2 exit 0 + artifact fails its check -> NOT complete, later stage untouched", a.status() not in ("done", "complete") and runs(tmp, "after") == 0,
        f"status={a.status()} later_stage_ran={runs(tmp,'after')}x")

# ---------- AC3 ----------
with tempfile.TemporaryDirectory() as tmp:
    a = Adapter(tmp, [{"id": "A", "argv": argv_count(tmp, "A")}, {"id": "B", "argv": argv_count(tmp, "B")}])
    a.run(); h1 = sha(a.state); a.run(); h2 = sha(a.state)
    rec("AC3a finished task re-run: no stage executes", runs(tmp, "A") == 1 and runs(tmp, "B") == 1, f"A={runs(tmp,'A')} B={runs(tmp,'B')}")
    rec("AC3b finished task re-run: state bytes unchanged", h1 == h2, f"{h1[:8]} vs {h2[:8]}")

# ---------- AC4 ----------
with tempfile.TemporaryDirectory() as tmp:
    a = Adapter(tmp, [{"id": "slow", "argv": argv_count(tmp, "slow", "import time;time.sleep(4)")}])
    p1 = a.start(); time.sleep(1.0)
    p2 = a.start(); p2.wait(timeout=30); p1.wait(timeout=30)
    rec("AC4 second concurrent runner refused (single writer)", runs(tmp, "slow") == 1, f"stage executed {runs(tmp,'slow')}x by 2 concurrent runners; 2nd rc={p2.returncode}")

# ---------- AC7 ----------
with tempfile.TemporaryDirectory() as tmp:
    a = Adapter(tmp, [{"id": "slow", "argv": argv_count(tmp, "slow", "import time;time.sleep(6)")}])
    p = a.start(); time.sleep(1.0); p.send_signal(signal.SIGTERM); rc = p.wait(timeout=30)
    rec("AC7 SIGTERM -> exit 143 and the state says 'interrupted'", rc == 143 and a.mentions_interrupt(), f"rc={rc} interrupted_recorded={a.mentions_interrupt()}")

# ---------- Approval gate ----------
with tempfile.TemporaryDirectory() as tmp:
    steps = [{"id": "prep", "argv": argv_count(tmp, "prep")}, {"id": "approve", "gate": True}, {"id": "danger", "argv": argv_count(tmp, "danger")}]
    a = Adapter(tmp, steps)
    if WHICH == "spike":
        rec("APPROVAL gate stays closed on re-run with no human action", None, "NOT IMPLEMENTED in M0 (AC6 is open) -> not counted")
    else:
        a.run(); s1 = a.status(); a.run(); s2 = a.status()
        rec("APPROVAL gate stays closed on re-run with no human action", runs(tmp, "danger") == 0,
            f"run1={s1}; plain re-run={s2}; irreversible stage executed {runs(tmp,'danger')}x")

counted = [(n, o) for n, o, _ in res if o is not None]
print(f"\nSUMMARY[{WHICH}]: {sum(1 for _, o in counted if o)}/{len(counted)} pass ({len(res)-len(counted)} not implemented)")
json.dump([{"probe": n, "pass": o, "detail": d} for n, o, d in res], open(os.path.expanduser(f"~/study/sources/step0/result_{WHICH}.json"), "w"), ensure_ascii=False, indent=1)
