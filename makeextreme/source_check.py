"""Primary-source check for a report artifact, usable as a stage `check`.

    python -m makeextreme.source_check REPORT.md SOURCES.json

Passes (exit 0) only if
  1. every line of REPORT that states a figure (a digit) or a quotation carries a
     citation marker like [1];
  2. every marker resolves to an entry in SOURCES.json with a non-empty `url` and
     `locator` (page, section, timestamp, table row);
  3. every cited entry has `checked_by` set and different from the top-level `author`
     (the writer does not verify its own sources) and `verdict` == "confirmed".

Exit 1 lists the failing lines and ids. Structure only: it does not fetch URLs; the
independent checker records what it found in SOURCES.json.
Idea source: Felix Rieseberg on Silicon Valley Girl (2026-10-20) -- have the model
check report figures against their primary source.
"""
import json, re, sys

MARK = re.compile(r"\[(\d+)\]")
FIGURE = re.compile(r"\d")
QUOTE = re.compile(r"[\"\u201c\u201e\u300c].{3,}?[\"\u201d\u201c\u300d]")
SKIP = re.compile(r"^\s*(#|```|\|?\s*-{3,})")  # headings, fences, table rules


def problems(report_text, sources):
    out = []
    author = (sources.get("author") or "").strip()
    entries = {str(k): v for k, v in (sources.get("sources") or {}).items()}
    cited = set()
    for n, line in enumerate(report_text.splitlines(), 1):
        if not line.strip() or SKIP.match(line):
            continue
        marks = MARK.findall(line)
        bare = MARK.sub("", line)
        if (FIGURE.search(bare) or QUOTE.search(bare)) and not marks:
            out.append(f"line {n}: figure or quote without citation")
        cited.update(marks)
    for i in sorted(cited, key=int):
        e = entries.get(i)
        if not e:
            out.append(f"[{i}]: no such source")
            continue
        for k in ("url", "locator"):
            if not str(e.get(k) or "").strip():
                out.append(f"[{i}]: missing {k}")
        who = str(e.get("checked_by") or "").strip()
        if not who:
            out.append(f"[{i}]: not checked")
        elif author and who == author:
            out.append(f"[{i}]: checked by the author")
        if e.get("verdict") != "confirmed":
            out.append(f"[{i}]: verdict is {e.get('verdict')!r}, not 'confirmed'")
    return out


def main(argv):
    if len(argv) != 2:
        print("usage: python -m makeextreme.source_check REPORT SOURCES.json", file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as f:
        text = f.read()
    with open(argv[1], encoding="utf-8") as f:
        sources = json.load(f)
    bad = problems(text, sources)
    for p in bad:
        print(p)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
