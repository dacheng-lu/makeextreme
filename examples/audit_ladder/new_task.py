#!/usr/bin/env python3
"""Create an audit-ladder task directory for makeextreme.

    python new_task.py <task_dir> --repo <git repo> --base <rev> --suite "<test command>" --goal "<what the change is for>" \\
        --criterion "<acceptance criterion>" [--criterion ...] --cheap-cmd "<shell>" --final-cmd "<shell>" [--head REV]
        [--pack-max-chars N] [--final-max-chars N]

Writes bin/ (the stage commands), audit.json, brief.json, cheap_cmd.sh, final_cmd.sh, an empty replays.json and stages.json. Then:

    python -m makeextreme run <task_dir>        # scope, tier0 (no model), cheap, findings; stops at `replay` if a finding has no replay
    # write replays.json: {"F1": {"status": "confirmed" | "not_reproduced", "evidence": "what you ran and saw"}}
    python -m makeextreme run <task_dir>        # replay, final_prompt, then waits for approval (exit 4)
    python -m makeextreme approve <task_dir> final_audit
    python -m makeextreme run <task_dir>        # the expensive model runs once (exit 0); the report is final_report.txt

The model commands read $AUDIT_PROMPT and print a report; they run with $AUDIT_REPO, $AUDIT_BASE, $AUDIT_HEAD set. Give them a read-only
view of a clean copy of the repository without its git history (history can contain the fix). What they print is parsed, never executed.
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def stages(py):
    run = lambda step: "%s bin/audit_ladder.py %s" % (py, step)
    chk = lambda step: "%s bin/audit_ladder.py check %s" % (py, step)
    code = ["bin/audit_ladder.py", "bin/slice_diff.py"]
    return [
        {"id": "scope", "run": run("scope"), "check": chk("scope"), "deps": ["audit.json"] + code, "outputs": ["scope.json"]},
        {"id": "tier0", "run": run("tier0"), "check": chk("tier0"), "deps": ["scope.json", "audit.json"] + code, "outputs": ["tier0.json", "pack.md"]},
        {"id": "cheap", "run": run("cheap"), "check": chk("cheap"), "deps": ["pack.md", "scope.json", "audit.json", "cheap_cmd.sh"] + code,
         "outputs": ["cheap_prompt.md", "cheap_report.txt"]},
        {"id": "findings", "run": run("findings"), "check": chk("findings"), "deps": ["cheap_report.txt"] + code, "outputs": ["findings.json"]},
        {"id": "replay", "run": run("replay"), "check": chk("replay"), "deps": ["findings.json", "replays.json", "brief.json"] + code, "outputs": ["closed.json"]},
        {"id": "final_prompt", "run": run("final_prompt"), "check": chk("final_prompt"),
         "deps": ["brief.json", "scope.json", "tier0.json", "closed.json", "cheap_report.txt"] + code, "outputs": ["final_prompt.md"]},
        {"id": "final_audit", "run": run("final"), "check": chk("final"), "deps": ["final_prompt.md", "audit.json", "final_cmd.sh"] + code,
         "outputs": ["final_report.txt"], "approval": "required"},
    ]


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("task_dir")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--suite", required=True)
    ap.add_argument("--goal", required=True)
    ap.add_argument("--criterion", action="append", default=[])
    ap.add_argument("--cheap-cmd", required=True)
    ap.add_argument("--final-cmd", required=True)
    ap.add_argument("--pack-max-chars", type=int, default=60000)
    ap.add_argument("--final-max-chars", type=int, default=12000)
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args(argv)
    d = os.path.abspath(a.task_dir)
    os.makedirs(os.path.join(d, "bin"), exist_ok=True)
    for name in ("audit_ladder.py", "slice_diff.py"):
        shutil.copyfile(os.path.join(HERE, "bin", name), os.path.join(d, "bin", name))

    def write(name, text):
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(text)

    write("audit.json", json.dumps({"repo": os.path.abspath(a.repo), "base": a.base, "head": a.head, "suite_cmd": a.suite,
                                    "pack_max_chars": a.pack_max_chars}, indent=1) + "\n")
    write("brief.json", json.dumps({"goal": a.goal, "criteria": a.criterion or ["the suite passes"], "final_max_chars": a.final_max_chars,
                                    "block_on": ["BLOCKER", "MAJOR"]}, indent=1) + "\n")
    write("cheap_cmd.sh", a.cheap_cmd + "\n")
    write("final_cmd.sh", a.final_cmd + "\n")
    if not os.path.exists(os.path.join(d, "replays.json")):
        write("replays.json", "{}\n")
    write("stages.json", json.dumps(stages(a.python), indent=1) + "\n")
    print("task written to %s" % d)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
