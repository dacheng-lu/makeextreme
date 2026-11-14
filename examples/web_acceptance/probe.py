#!/usr/bin/env python3
"""Check the dev-lu release-digest state selector in a local headless browser.

The page is run once with a wide window and once with a narrow one, and for each run
the probe clicks the three state buttons of the release-digest demo, then reads back
`aria-pressed` and `hidden` from the same document. The browser's sandbox stays on:
a browser that cannot start is `blocked`, it is never retried with `--no-sandbox`.
"""
import html.parser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

STATES = ('checked', 'changed', 'restored')
# Desktop and mobile window sizes. A headless browser may clamp the window (Chrome 157
# renders the 390px request at 500px), so what the page really saw is read back and
# recorded; the gate needs a wide viewport and a narrow one below the site's breakpoint.
REQUESTED = ((1280, 800), (390, 844))
WIDE_MIN, NARROW_MAX = 1000, 600
BROWSERS = ('chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable')
FLAGS = ('--headless', '--disable-gpu', '--disable-dev-shm-usage',
         '--disable-background-networking', '--host-resolver-rules=MAP * ~NOTFOUND')

SCRIPT = (r'''<script>
window.addEventListener('load', () => {
  const result = {viewport: [window.innerWidth, window.innerHeight], checks: []};
  for (const id of %s) {
    const button = document.querySelector('[data-digest="' + id + '"]');
    const panel = document.querySelector('[data-digest-panel="' + id + '"]');
    if (button) button.click();
    const buttons = [...document.querySelectorAll('[data-digest]')];
    const panels = [...document.querySelectorAll('[data-digest-panel]')];
    result.checks.push({state: id, ok: !!button && !!panel &&
      buttons.length === 3 && panels.length === 3 &&
      buttons.every(b => b.getAttribute('aria-pressed') === String(b === button)) &&
      panels.every(p => p.hidden === (p !== panel))});
  }
  const marker = document.createElement('pre'); marker.id = 'acceptance-result';
  marker.textContent = JSON.stringify(result); document.body.appendChild(marker);
});
</script>''' % json.dumps(list(STATES)))


class Marker(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(); self.inside = False; self.text = ''
    def handle_starttag(self, tag, attrs):
        if tag == 'pre' and ('id', 'acceptance-result') in attrs: self.inside = True
    def handle_endtag(self, tag):
        if tag == 'pre': self.inside = False
    def handle_data(self, data):
        if self.inside: self.text += data


def write(status, reason, checks=None, browser=None):
    doc = {'status': status, 'reason': reason, 'browser': browser or {},
           'flags': [] if browser is None else list(FLAGS), 'checks': checks or []}
    Path('report.json').write_text(json.dumps(doc, indent=2) + '\n')


def find_browser():
    """The browser to launch: WEB_ACCEPTANCE_BROWSER if set, else the first one on PATH."""
    wanted = os.environ.get('WEB_ACCEPTANCE_BROWSER')
    for name in ((wanted,) if wanted else BROWSERS):
        found = shutil.which(name)
        if found:
            return found
    return None


def version(browser):
    try:
        done = subprocess.run([browser, '--version'], text=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 'unknown'
    text = (done.stdout or done.stderr).strip().splitlines()
    return text[0][:160] if text else 'unknown'


def tail(text, limit=200):
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return ' | '.join(lines[-1:])[:limit]


def viewport_of(value):
    """A [width, height] pair of positive integers, or None."""
    if (isinstance(value, list) and len(value) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in value)):
        return value
    return None


def dump_dom(browser, profile, width, height, uri):
    """The browser's DOM dump. A launch that dies before the page produced its marker is
    tried once more: Chrome's zygote exits 21 with "Failed sending zygote boot message" on a
    loaded host (measured here under memory pressure), which says nothing about the page.
    A browser that still cannot start is reported, never retried with --no-sandbox."""
    for attempt in (1, 2):
        result = subprocess.run([browser, *FLAGS, f'--user-data-dir={profile}-{attempt}',
                                 f'--window-size={width},{height}', '--dump-dom', uri],
                                text=True, capture_output=True, timeout=60)
        if result.returncode == 0 or 'id="acceptance-result"' in result.stdout or attempt == 2:
            return result
        time.sleep(1)
    return result


def run():
    browser = find_browser()
    if not browser:
        wanted = os.environ.get('WEB_ACCEPTANCE_BROWSER')
        write('blocked', 'browser executable not found' + (f': {wanted}' if wanted else ''))
        return
    record = {'path': browser, 'version': version(browser), 'sandbox': 'enabled'}
    try:
        with tempfile.TemporaryDirectory(prefix='web-regression-') as d:
            root = Path(d); shutil.copytree('site', root / 'site')
            page = root / 'site/index.html'
            source = page.read_text(encoding='utf-8')
            if '</body>' not in source:
                write('fail', 'index.html has no closing body', browser=record); return
            page.write_text(source.replace('</body>', SCRIPT + '</body>', 1), encoding='utf-8')
            checks = []
            for width, height in REQUESTED:
                result = dump_dom(browser, root / f'profile-{width}', width, height, page.as_uri())
                marker = Marker(); marker.feed(result.stdout)
                if not marker.text:
                    if result.returncode:
                        write('blocked', f'browser exited {result.returncode} at {width}x{height} '
                              f'without rendering the page: ' + tail(result.stderr), browser=record)
                        return
                    write('fail', f'probe marker missing at {width}x{height}', browser=record); return
                observed = json.loads(marker.text)
                seen = viewport_of(observed.get('viewport'))
                if seen is None:
                    write('fail', f'the page reported no viewport at {width}x{height}',
                          browser=record); return
                checks.append({'requested': [width, height], 'viewport': seen,
                               'states': observed.get('checks')})
            ok = all(item.get('state') in STATES and item.get('ok') is True
                     for view in checks for item in view['states'] or [])
            wide, narrow = checks[0]['viewport'][0], checks[1]['viewport'][0]
            why = []
            if not ok: why.append('a digest state did not match its button')
            if wide < WIDE_MIN: why.append(f'the wide window rendered {wide}px, below {WIDE_MIN}px')
            if narrow > NARROW_MAX:
                why.append(f'the narrow window rendered {narrow}px, above the {NARROW_MAX}px breakpoint')
            write('fail' if why else 'pass', '; '.join(why) or 'digest state selector', checks, record)
    except (OSError, subprocess.TimeoutExpired) as exc:
        write('blocked', f'browser execution unavailable: {exc}', browser=record)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        write('fail', f'invalid browser observation: {exc}', browser=record)


def state_ok(view):
    states = view.get('states')
    return (isinstance(states, list) and [s.get('state') for s in states] == list(STATES)
            and all(s.get('ok') is True for s in states))


def gate():
    """True only for a report that this probe itself would have produced on a real pass."""
    try:
        report = json.loads(Path('report.json').read_text())
        views = report['checks']
        browser = report['browser']
        flags = report.get('flags')
        return bool(report.get('status') == 'pass'
                    and isinstance(browser, dict) and isinstance(browser.get('path'), str)
                    and browser['path'] and browser.get('sandbox') == 'enabled'
                    and isinstance(flags, list) and '--no-sandbox' not in flags
                    and isinstance(views, list) and len(views) == len(REQUESTED)
                    and [v['requested'] for v in views] == [list(x) for x in REQUESTED]
                    and all(viewport_of(v['viewport']) for v in views)
                    and all(state_ok(v) for v in views)
                    and views[0]['viewport'][0] >= WIDE_MIN and views[1]['viewport'][0] <= NARROW_MAX)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        return False  # a report that is not shaped like this probe's own is no evidence


if __name__ == '__main__':
    if sys.argv[1:] == ['run']: run()
    elif sys.argv[1:] == ['skip']: write('skipped', 'browser execution explicitly skipped')
    elif sys.argv[1:] == ['check']: sys.exit(0 if gate() else 1)
    else: sys.exit('usage: probe.py run|skip|check')
