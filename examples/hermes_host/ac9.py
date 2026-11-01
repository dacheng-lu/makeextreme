"""AC9: a Hermes host runs a real stage in a scrubbed environment and its answer is captured and checked.

    python ac9.py [--provider ollama-cloud] [--model deepseek-v4.1-flash:1017] [--work DIR]

On demand, not in CI: it makes one tiny model call per run (about 4 s), so use a provider that is part of your
subscription. Two tasks run through `python -m makeextreme run`:

  good    stage `scrub` proves the scrubbed environment (a canary secret set in the runner's environment must not
          reach the stage), stage `ask` runs `hermes chat -q ... --oneshot` under `env -i` and the check reads
          the captured answer.
  broken  the same `ask` stage with a model name that does not exist. The stage must FAIL (exit 2) and leave no
          answer: a check that cannot fail would make the good run mean nothing.
  leaky   the `scrub` stage WITHOUT `env -i`. Its check must FAIL (exit 2): proof that the canary test can see a
          leak, so a pass of the good run means the environment really was scrubbed.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CANARY = "MX_CANARY_SECRET"
PROMPT = "Reply with exactly the word OK and nothing else."


def spec(provider, model, scrubbed=True):
    clean = 'env -i HOME="$HOME" PATH="$PATH"'
    return [
        {"id": "scrub",
         "run": "%s sh -c 'env | sort' > env.part && mv env.part env.txt" % (clean if scrubbed else ""),
         "check": "test -s env.txt && grep -q '^HOME=' env.txt && ! grep -q %s env.txt" % CANARY},
        {"id": "ask",
         "run": "%s hermes chat -q '%s' --oneshot -Q --provider %s -m %s --max-turns 1 > answer.part "
                "&& mv answer.part answer.txt" % (clean, PROMPT, provider, model),
         "check": "test \"$(grep -v '^$' answer.txt | head -n 1)\" = OK",
         "deps": ["env.txt"]},
    ]


def mx(d, *args):
    env = dict(os.environ, **{CANARY: "canary-must-not-leak"})
    return subprocess.run([sys.executable, "-m", "makeextreme", *args, d], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=240)


def make(d, provider, model, scrubbed=True):
    os.makedirs(d)
    with open(os.path.join(d, "stages.json"), "w") as f:
        json.dump(spec(provider, model, scrubbed), f)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="ollama-cloud")
    ap.add_argument("--model", default="deepseek-v4.1-flash:1017")
    ap.add_argument("--work", default=os.path.expanduser("~/ac10work/ac9"))
    a = ap.parse_args(argv)
    shutil.rmtree(a.work, ignore_errors=True)
    good, broken, leaky = (os.path.join(a.work, n) for n in ("good", "broken", "leaky"))
    results = []

    make(good, a.provider, a.model)
    r = mx(good, "run")
    results.append(("good: run completes (exit 0)", r.returncode == 0,
                    "exit %d%s" % (r.returncode, " " + r.stderr[-150:] if r.returncode else "")))
    env_txt = open(os.path.join(good, "env.txt")).read() if os.path.exists(os.path.join(good, "env.txt")) else ""
    names = sorted(l.split("=")[0] for l in env_txt.split("\n") if l)
    shell_added = {"PWD", "OLDPWD", "SHLVL", "_"}  # what sh itself adds to an empty environment
    results.append(("good: the stage saw a scrubbed environment (HOME and PATH, plus what sh adds)",
                    CANARY not in env_txt and {"HOME", "PATH"} <= set(names) and set(names) <= {"HOME", "PATH"} | shell_added,
                    ",".join(names)))
    answer = open(os.path.join(good, "answer.txt")).read() if os.path.exists(os.path.join(good, "answer.txt")) else ""
    first = next((l for l in answer.split("\n") if l.strip()), "")
    results.append(("good: the captured answer starts with OK", first == "OK", repr(first)))
    state = json.load(open(os.path.join(good, "task.json")))
    results.append(("good: both stages done in the record",
                    all(state["stages"].get(s, {}).get("status") == "done" for s in ("scrub", "ask")), ""))

    make(broken, a.provider, "no-such-model-xyz")
    r = mx(broken, "run")
    results.append(("broken: a wrong model makes the stage fail (exit 2)", r.returncode == 2, "exit %d" % r.returncode))
    results.append(("broken: no answer artifact is left behind", not os.path.exists(os.path.join(broken, "answer.txt")), ""))

    make(leaky, a.provider, a.model, scrubbed=False)
    r = mx(leaky, "run")
    results.append(("leaky: without `env -i` the canary check fails the stage (exit 2)", r.returncode == 2,
                    "exit %d" % r.returncode))
    results.append(("leaky: the canary really reached that stage",
                    CANARY in (open(os.path.join(leaky, "env.txt")).read() if os.path.exists(os.path.join(leaky, "env.txt")) else ""),
                    ""))

    width = max(len(x[0]) for x in results)
    for name, ok, note in results:
        print("%s  %-*s  %s" % ("PASS" if ok else "FAIL", width, name, note))
    ok = all(x[1] for x in results)
    print("\nAC9 %s (provider %s, model %s)" % ("PASS" if ok else "FAIL", a.provider, a.model))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
