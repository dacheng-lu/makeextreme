# Local web regression: release-digest selector

This optional, narrowly scoped example checks the existing release-digest state
selector on a **local snapshot of dev-lu.com**. It clicks the three state buttons in
a real browser at a wide and a narrow window size and checks that exactly the selected
button has `aria-pressed=true` and exactly its panel is unhidden. It is a regression
check of existing behavior, not evidence of a bug or a fix.

The snapshot is supplied by the caller and must include `index.html` and its local
assets. Symbolic links are refused: the copy lists every entry and reads it with
`O_NOFOLLOW`, so a link cannot pull a byte from outside the snapshot into the task,
even one created between the listing and the read. A `.git` entry (history, not
content) is not copied.

Requirements: Python 3, Linux with `/proc` for Makeextreme, and a local Chromium or
Chrome — `chromium`, `chromium-browser`, `google-chrome` or `google-chrome-stable` on
`PATH`, or `WEB_ACCEPTANCE_BROWSER=/path/to/browser`. Run only with a trusted
snapshot. The browser opens a temporary copy of `site/` through a `file:` URL with DNS
disabled and its own `--user-data-dir`, and **the sandbox stays on**: a browser that
cannot start its own sandbox is reported `blocked`, never retried with `--no-sandbox`.
This is not an isolation boundary for hostile page code. It does not publish, edit the
supplied snapshot, or require Node/MCP.

```sh
python3 examples/web_acceptance/new_task.py /path/to/site-snapshot /tmp/web-regression
python3 -m makeextreme run /tmp/web-regression
cat /tmp/web-regression/report.json
python3 -m makeextreme run /tmp/web-regression  # unchanged successful output is skipped
```

The JSON `status` is `pass`, `fail`, `blocked` (no browser, launch failure or timeout),
or `skipped` (explicit `--skip-browser` on task creation). Only `pass` satisfies the
stage check; inspect the report on any failed run. Creating with `--skip-browser`
deliberately leaves the stage incomplete. Delete `report.json` and rerun to exercise
output recovery. Changing the copied `site/` or `probe.py` invalidates the stage; an
old report may remain after a failed run, so use only the result of the current run.
For a fresh browser observation, delete the report and rerun even if dependencies did
not change.

The report states how it was produced: `browser` is the executable, its version
string and `"sandbox": "enabled"`; `flags` is the argument list the probe passes; each
entry of `checks` records the `requested` window size, the `viewport` the page really
saw, and the three states. A headless browser need not honour the request — measured
with Chrome 157, `--window-size=390,844` renders a 500px-wide viewport, and the height
of both windows is trimmed — so the recorded viewport is the measurement, not the
request.
The gate needs a wide viewport of at least 1000px and a narrow one of at most 600px
(the site's mobile breakpoint); when a browser renders the narrow request wider than
that the run is `fail`, because the narrow layout was not exercised.

## Proving the paths on a real browser

`tests/test_web_acceptance.py` replaces the browser with a stand-in: it checks the
probe's bookkeeping, not a browser. To see the real thing, give `verify_paths.py` a
snapshot and a browser:

```sh
python3 examples/web_acceptance/verify_paths.py /path/to/site-snapshot \
    --browser /usr/bin/google-chrome-stable --work /tmp/web-paths --json /tmp/web-paths.json
```

It runs the example's stage through `python -m makeextreme` and prints one line per
path: a real `pass`; a second run that runs no browser; an edited site that invalidates
the finished stage; an edited `report.json` that the gate rejects and the next run
replaces; a real `fail` for a temporary copy with one control removed and for one whose
click never reaches the page's handler; `blocked` with a `PATH` that holds no browser;
`skipped` with `--skip-browser`; and a symlinked `index.html`, asset, directory or site
path refused without copying anything. Exit 0 means every path was observed, 1 that one
was not, 3 that no browser was found (nothing is proven).

## What a pass does not prove

The browser probe injects a small observer into a temporary page copy, invokes DOM click
handlers and records DOM state. It does not test physical pointer or keyboard input,
rendering quality, actual device emulation, console errors, accessibility as a whole, or
production deployment. Browser state and screen captures are not retained. A `pass` is a
local observation, not an authenticated receipt. For Longhaul, a human can inspect a
successful current report and then register it via its existing
`checkpoint.py artifact` and `evidence` commands; no automatic adapter is provided.
