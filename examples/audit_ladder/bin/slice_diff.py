#!/usr/bin/env python3
"""slice_diff.py (the same code as the Hermes skill auditor-token-saver; tested here in tests/test_slice_diff.py): a deterministic context pack for an audit: only the functions a diff touched, who calls them, which tests name them.

usage: slice_diff.py <repo> <base> [<head>] [--max-chars N] [--json]
Reads git only (never writes). Python files are cut into the enclosing function/method of every changed line (ast, head version);
a change outside any function is the unit `<module>`; an unparseable file comes whole. Callers are matched by name
(`f()` and `x.f()`), so a hit can be a different function of the same name: a lead, not a proof. Other files are only listed.
Token counts are chars/4: an estimate. Exit 0 ok, 2 git/usage error.
"""
import argparse
import ast
import json
import re
import subprocess
import sys


def git(repo, *a):
    r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("git %s failed: %s" % (" ".join(a[:2]), r.stderr.strip()[:200]))
    return r.stdout


def changed_files(repo, base, head):
    out = git(repo, "diff", "--name-status", "--no-renames", "%s..%s" % (base, head))
    res = []
    for line in out.splitlines():
        st, path = line.split("\t", 1)
        res.append((path, {"A": "added", "M": "modified", "D": "deleted"}.get(st[0], st)))
    return res


def changed_ranges(repo, base, head, path):
    """New-side line ranges of a file's hunks (git diff -U0)."""
    out = git(repo, "diff", "-U0", "--no-renames", "%s..%s" % (base, head), "--", path)
    rs = []
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", out, re.M):
        start, n = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
        rs.append((start, start + max(n, 1) - 1))
    return rs


def functions(tree):
    """(qualified name, first line, last line) of every function; methods carry their class."""
    found = []

    def walk(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = min([ch.lineno] + [d.lineno for d in ch.decorator_list])
                found.append((prefix + ch.name, start, ch.end_lineno))
                walk(ch, prefix + ch.name + ".")
            elif isinstance(ch, ast.ClassDef):
                walk(ch, prefix + ch.name + ".")
            else:
                walk(ch, prefix)
    walk(tree, "")
    return found


def innermost(funcs, line):
    best = None
    for name, a, b in funcs:
        if a <= line <= b and (best is None or (b - a) < (best[2] - best[1])):
            best = (name, a, b)
    return best


def units_for(repo, base, head, path, status):
    src = git(repo, "show", "%s:%s" % (head, path))
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return [{"file": path, "name": "<whole file: not parseable>", "start": 1, "end": len(lines), "source": src}]
    funcs = functions(tree)
    if status == "added":
        ranges = [(1, max(len(lines), 1))]
    else:
        ranges = changed_ranges(repo, base, head, path)
    picked, module_lines = {}, []
    for a, b in ranges:
        for ln in range(a, b + 1):
            f = innermost(funcs, ln)
            if f:
                picked[f[0]] = f
            elif status != "added" or lines[ln - 1].strip():
                module_lines.append(ln)
    res = []
    for name, a, b in sorted(picked.values(), key=lambda t: t[1]):
        res.append({"file": path, "name": name, "start": a, "end": b, "source": "\n".join(lines[a - 1:b])})
    if module_lines and status != "added":
        runs = []  # one unit per run of consecutive changed lines: an import at the top and a constant at the bottom are two units
        for ln in sorted(set(module_lines)):
            if runs and ln == runs[-1][1] + 1:
                runs[-1][1] = ln
            else:
                runs.append([ln, ln])
        for a, b in runs:
            res.append({"file": path, "name": "<module>", "start": a, "end": b, "source": "\n".join(lines[a - 1:b])})
    return res


def callers_of(repo, head, names):
    simple = {n.split(".")[-1] for n in names}
    found = []
    for path in git(repo, "ls-tree", "-r", "--name-only", head).splitlines():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(git(repo, "show", "%s:%s" % (head, path)))
        except (SyntaxError, RuntimeError):
            continue
        for qn, a, b in functions(tree):
            node_calls = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and getattr(n, "lineno", 0) >= a and getattr(n, "end_lineno", 0) <= b:
                    f = n.func
                    node_calls.add(f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None)
            hit = sorted(simple & node_calls)
            if hit and qn.split(".")[-1] not in simple:
                found.append({"file": path, "caller": qn, "calls": hit})
    return found


def tests_naming(repo, head, names):
    simple = {n.split(".")[-1] for n in names if not n.startswith("<")}
    found = []
    for path in git(repo, "ls-tree", "-r", "--name-only", head).splitlines():
        if path.endswith(".py") and re.search(r"(^|/)(tests?/|test_)", path):
            txt = git(repo, "show", "%s:%s" % (head, path))
            if any(re.search(r"\b%s\b" % re.escape(n), txt) for n in simple):
                found.append(path)
    return sorted(found)


def build(repo, base, head="HEAD", max_chars=None):
    units, other, full = [], [], 0
    for path, status in changed_files(repo, base, head):
        if path.endswith(".py") and status != "deleted":
            full += len(git(repo, "show", "%s:%s" % (head, path)))
            units += units_for(repo, base, head, path, status)
        else:
            other.append({"file": path, "status": status})
    names = [u["name"] for u in units]
    callers = [c for c in callers_of(repo, head, [n for n in names if not n.startswith("<")])] if names else []
    tests = tests_naming(repo, head, names) if names else []
    md, left = [], 0
    body = ["## Changed units (%d)" % len(units)]
    for u in units:
        block = "### %s :: %s (lines %d-%d)\n```python\n%s\n```" % (u["file"], u["name"], u["start"], u["end"], u["source"])
        if max_chars is not None and sum(len(x) for x in body) + len(block) > max_chars:
            left += 1
            continue
        body.append(block)
    if left:
        body.append("left out: %d unit(s) (over --max-chars %d); read those files directly" % (left, max_chars))
    md += body
    md.append("## Callers by name, a lead not a proof (%d)" % len(callers))
    md += ["- %s :: %s calls %s" % (c["file"], c["caller"], ", ".join(c["calls"])) for c in callers]
    md.append("## Tests that name a changed function (%d)" % len(tests))
    md += ["- " + t for t in tests]
    md.append("## Other changed files (%d)" % len(other))
    md += ["- %s (%s)" % (o["file"], o["status"]) for o in other]
    text = "\n".join(md)
    pack = len(text)
    ratio = (pack / full) if full else None
    text += "\n\n_pack %d chars (about %d tokens, estimate chars/4); the changed .py files are %d chars whole%s._\n" % (
        pack, pack // 4, full, ("; pack is %.1f%% of that" % (100 * ratio)) if ratio is not None else "")
    return {"markdown": text, "units": units, "callers": callers, "tests": tests, "other": other,
            "pack_chars": pack, "full_chars": full, "ratio": ratio}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("base")
    ap.add_argument("head", nargs="?", default="HEAD")
    ap.add_argument("--max-chars", type=int)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        p = build(a.repo, a.base, a.head, a.max_chars)
    except RuntimeError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in p.items() if k != "markdown"}, indent=1) if a.json else p["markdown"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
