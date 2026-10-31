#!/usr/bin/env python3
"""Step-0 trial: DVC 3.67.1 (dvc repro) against the same scenarios as probe_step0.py. Black-box, tool unedited.
Run: PYTHONDONTWRITEBYTECODE=1 ~/.hermes/hermes-agent/venv/bin/python probe_dvc.py
"""
import hashlib, json, os, shlex, signal, subprocess, sys, tempfile, time

DVC = os.path.expanduser("~/.hermes/cache/scratch/dvcenv/bin/dvc")
PYX = os.path.expanduser("~/.hermes/cache/scratch/dvcenv/bin/python")
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


def runs(tmp, n):
    p = os.path.join(tmp, n + ".runs")
    return len(open(p).read().split()) if os.path.exists(p) else 0


def env():
    e = dict(os.environ); e["DVC_NO_ANALYTICS"] = "true"; e["PYTHONDONTWRITEBYTECODE"] = "1"; return e


def proj(tmp, stages):
    """stages: list of (id, python-body, deps, outs)"""
    subprocess.run([DVC, "init", "--no-scm", "-q"], cwd=tmp, env=env(), check=True, capture_output=True)
    y = ["stages:"]
    for sid, body, deps, outs in stages:
        code = f"open({os.path.join(tmp, sid + '.runs')!r},'a').write('x\\n');{body}"
        sc = os.path.join(tmp, f"stage_{sid}.py")
        open(sc, "w").write(code + "\n")
        y.append(f"  {sid}:")
        y.append(f"    cmd: {PYX} {sc}")
        deps = list(deps) + [os.path.basename(sc)]   # the stage script is a declared dependency (normal DVC practice)
        y.append("    deps: [" + ", ".join(deps) + "]")
        if outs: y.append("    outs: [" + ", ".join(outs) + "]")
    open(os.path.join(tmp, "dvc.yaml"), "w").write("\n".join(y) + "\n")


def repro(tmp, **kw):
    return subprocess.Popen([DVC, "repro"], cwd=tmp, env=env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)


def wr(f, s="ok"):
    return f"open({f!r},'w').write({s!r})"


# AC1
with tempfile.TemporaryDirectory() as tmp:
    pidf = os.path.join(tmp, "B.pid"); bruns = os.path.join(tmp, "B.runs")
    proj(tmp, [
        ("A", wr("a.out"), [], ["a.out"]),
        ("B", f"import os,time;open({pidf!r},'w').write(str(os.getpid()));n=len(open({bruns!r}).read().split());time.sleep(60 if n==1 else 0);" + wr("b.out"), ["a.out"], ["b.out"]),
        ("C", wr("c.out"), ["b.out"], ["c.out"])])
    p = repro(tmp)
    for _ in range(300):
        if os.path.exists(pidf) and open(pidf).read().strip(): break
        time.sleep(0.1)
    child = int(open(pidf).read()); p.kill(); p.wait(); time.sleep(0.5)
    r = repro(tmp); r.wait(timeout=90)
    gone = not alive(child)
    rec("AC1a after resume, killed run's child process is gone (reaped)", gone, f"child {child} alive_after_resume={not gone}")
    if not gone: os.kill(child, signal.SIGKILL)
    rec("AC1b completed stage A not re-run", runs(tmp, "A") == 1, f"A ran {runs(tmp,'A')}x")
    rec("AC1c crashed stage B ran exactly 2x", runs(tmp, "B") == 2, f"B ran {runs(tmp,'B')}x")
    rec("AC1d pipeline completes", os.path.exists(os.path.join(tmp, "c.out")) and r.returncode == 0, f"rc={r.returncode} c.out={os.path.exists(os.path.join(tmp,'c.out'))}; stderr={r.stderr.read().decode()[-160:]!r}")

# AC2 (content wrong) + AC2' (output missing)
with tempfile.TemporaryDirectory() as tmp:
    proj(tmp, [("produce", wr("out.txt", "PARTIAL 159/272"), [], ["out.txt"]), ("after", wr("after.out"), ["out.txt"], ["after.out"])])
    r = repro(tmp); r.wait(timeout=60)
    rec("AC2 exit 0 + artifact content wrong (needs content check) -> NOT complete", runs(tmp, "after") == 0, f"later stage ran {runs(tmp,'after')}x, rc={r.returncode} (DVC only checks that declared outs EXIST)")
with tempfile.TemporaryDirectory() as tmp:
    proj(tmp, [("produce", "pass", [], ["out.txt"]), ("after", wr("after.out"), ["out.txt"], ["after.out"])])
    r = repro(tmp); r.wait(timeout=60)
    rec("AC2' exit 0 + declared output MISSING -> NOT complete (native existence check)", runs(tmp, "after") == 0 and r.returncode != 0, f"later ran {runs(tmp,'after')}x rc={r.returncode}")

# AC3
with tempfile.TemporaryDirectory() as tmp:
    proj(tmp, [("A", wr("a.out"), [], ["a.out"]), ("B", wr("b.out"), ["a.out"], ["b.out"])])
    repro(tmp).wait(timeout=60); h1 = sha(os.path.join(tmp, "dvc.lock")); repro(tmp).wait(timeout=60); h2 = sha(os.path.join(tmp, "dvc.lock"))
    rec("AC3a finished task re-run: no stage executes", runs(tmp, "A") == 1 and runs(tmp, "B") == 1, f"A={runs(tmp,'A')} B={runs(tmp,'B')}")
    rec("AC3b finished task re-run: dvc.lock bytes unchanged", h1 == h2, f"{(h1 or 'none')[:8]} vs {(h2 or 'none')[:8]}")

# AC4
with tempfile.TemporaryDirectory() as tmp:
    proj(tmp, [("slow", "import time;time.sleep(5);" + wr("s.out"), [], ["s.out"])])
    p1 = repro(tmp); time.sleep(1.5); p2 = repro(tmp); p2.wait(timeout=60); p1.wait(timeout=60)
    rec("AC4 second concurrent runner refused", runs(tmp, "slow") == 1, f"stage executed {runs(tmp,'slow')}x; 2nd rc={p2.returncode}; msg={p2.stderr.read().decode()[-140:]!r}")

# AC7
with tempfile.TemporaryDirectory() as tmp:
    proj(tmp, [("slow", "import time;time.sleep(8);" + wr("s.out"), [], ["s.out"])])
    p = repro(tmp); time.sleep(2.0); p.send_signal(signal.SIGTERM); rc = p.wait(timeout=60)
    seen = False
    for root, _, fs in os.walk(tmp):
        for f in fs:
            try:
                if "interrupt" in open(os.path.join(root, f), errors="ignore").read().lower(): seen = True
            except Exception: pass
    rec("AC7 SIGTERM -> exit 143 and a persisted 'interrupted' record", rc == 143 and seen, f"rc={rc} interrupted_recorded={seen}")

# Approval
rec("APPROVAL gate (pause for human, stay closed until approval)", None, "DVC has no approval/gate concept -> not counted")

# AC5 (DVC's home turf): change an artifact, only the dependent stage must re-run
with tempfile.TemporaryDirectory() as tmp:
    proj(tmp, [("A", wr("a.out", "v1"), [], ["a.out"]), ("B", wr("b.out"), ["a.out"], ["b.out"]), ("X", wr("x.out"), [], ["x.out"])])
    repro(tmp).wait(timeout=60)
    # edit stage A's script (a declared dep) -> A and its dependent B must re-run, independent X must not
    sa = os.path.join(tmp, "stage_A.py"); body = open(sa).read(); open(sa, "w").write(body.replace("v1", "v2"))
    repro(tmp).wait(timeout=60)
    rec("AC5 changed stage -> only dependents re-run (A,B again; independent X not)", runs(tmp, "A") == 2 and runs(tmp, "B") == 2 and runs(tmp, "X") == 1, f"A={runs(tmp,'A')} B={runs(tmp,'B')} X={runs(tmp,'X')}")

counted = [(n, o) for n, o, _ in res if o is not None]
print(f"\nSUMMARY[dvc]: {sum(1 for _, o in counted if o)}/{len(counted)} pass ({len(res)-len(counted)} not applicable)")
json.dump([{"probe": n, "pass": o, "detail": d} for n, o, d in res], open(os.path.expanduser("~/study/sources/step0/result_dvc.json"), "w"), ensure_ascii=False, indent=1)
