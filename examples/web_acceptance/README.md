# Local web regression: release-digest selector

This optional, narrowly scoped example checks the existing release-digest state
selector on a **local snapshot of dev-lu.com**. It clicks the three state buttons
at desktop and mobile window sizes and checks that exactly the selected button
has `aria-pressed=true` and exactly its panel is unhidden. It is a regression
check of existing behavior, not evidence of a bug or a fix. The snapshot must
include `index.html` and its local assets; the snapshot is supplied by the caller.
Symbolic links in the snapshot path or contents (including `index.html`) are refused.
The snapshot must remain unchanged while it is copied.

Requirements: Python 3, Linux with `/proc` for Makeextreme, and a working local
Chromium executable (`chromium`, `chromium-browser`, or `google-chrome`). Run
only with a trusted snapshot. Chromium opens a temporary copy through `file:`;
DNS is disabled for the probe. This is not an isolation boundary for hostile
page code. It does not publish, edit the supplied snapshot, or require Node/MCP.

```sh
python3 examples/web_acceptance/new_task.py /path/to/site-snapshot /tmp/web-regression
python3 -m makeextreme run /tmp/web-regression
cat /tmp/web-regression/report.json
python3 -m makeextreme run /tmp/web-regression  # unchanged successful output is skipped
```

The JSON `status` is `pass`, `fail`, `blocked` (browser unavailable, launch
failure or timeout), or `skipped` (explicit `--skip-browser` on task creation).
Only `pass` satisfies the stage check; inspect the report on any failed run.
Creating with `--skip-browser` deliberately leaves the stage incomplete. Delete
`report.json` and rerun to exercise output recovery. Changing the copied `site/`
or `probe.py` invalidates the stage; an old report may remain after a failed run,
so use only the result of the current run. For a fresh browser observation,
delete the report and rerun even if dependencies did not change.

The browser probe injects a small observer into a temporary page copy, invokes
DOM click handlers and records DOM state. It does not test physical pointer or
keyboard input, rendering quality, actual viewport dimensions, console errors,
accessibility as a whole, or production deployment. Browser state and screen
captures are not retained. A `pass` is a local observation, not an authenticated
receipt. For Longhaul, a human can inspect a successful current report and then
register it via its existing `checkpoint.py artifact` and `evidence` commands;
no automatic adapter is provided.
