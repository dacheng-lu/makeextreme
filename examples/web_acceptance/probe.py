#!/usr/bin/env python3
"""Check the dev-lu release-digest state selector in local headless Chromium."""
import html.parser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SCRIPT = r'''<script>
window.addEventListener('load', () => {
  const result = {checks: []};
  for (const id of ['checked', 'changed', 'restored']) {
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
</script>'''

class Marker(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(); self.inside = False; self.text = ''
    def handle_starttag(self, tag, attrs):
        if tag == 'pre' and ('id', 'acceptance-result') in attrs: self.inside = True
    def handle_endtag(self, tag):
        if tag == 'pre': self.inside = False
    def handle_data(self, data):
        if self.inside: self.text += data

def write(status, reason, checks=None):
    Path('report.json').write_text(json.dumps({'status': status, 'reason': reason, 'checks': checks or []}, indent=2) + '\n')

def run():
    browser = next((shutil.which(x) for x in ('chromium', 'chromium-browser', 'google-chrome') if shutil.which(x)), None)
    if not browser:
        write('blocked', 'Chromium executable not found'); return
    try:
        with tempfile.TemporaryDirectory(prefix='web-regression-') as d:
            root = Path(d); shutil.copytree('site', root / 'site')
            page = root / 'site/index.html'
            source = page.read_text(encoding='utf-8')
            if '</body>' not in source:
                write('fail', 'index.html has no closing body'); return
            page.write_text(source.replace('</body>', SCRIPT + '</body>', 1), encoding='utf-8')
            checks = []
            for width, height in ((1280, 800), (390, 844)):
                result = subprocess.run([browser, '--headless', '--no-sandbox', '--disable-gpu',
                    '--disable-dev-shm-usage', '--disable-background-networking',
                    '--host-resolver-rules=MAP * ~NOTFOUND',
                    '--user-data-dir=' + str(root / f'profile-{width}'),
                    f'--window-size={width},{height}', '--dump-dom', page.as_uri()],
                    text=True, capture_output=True, timeout=30)
                if result.returncode:
                    write('blocked', f'Chromium exited {result.returncode} at {width}x{height}'); return
                marker = Marker(); marker.feed(result.stdout)
                if not marker.text:
                    write('fail', f'probe marker missing at {width}x{height}'); return
                observed = json.loads(marker.text)['checks']
                checks.append({'viewport': [width, height], 'states': observed})
            ok = all(item['ok'] for view in checks for item in view['states'])
            write('pass' if ok else 'fail', 'digest state selector', checks)
    except (OSError, subprocess.TimeoutExpired) as exc:
        write('blocked', f'Browser execution unavailable: {exc}')
    except (ValueError, KeyError, TypeError) as exc:
        write('fail', f'Invalid browser observation: {exc}')

if __name__ == '__main__':
    if sys.argv[1:] == ['run']: run()
    elif sys.argv[1:] == ['skip']: write('skipped', 'browser execution explicitly skipped')
    elif sys.argv[1:] == ['check']:
        try:
            report = json.loads(Path('report.json').read_text())
            views = report.get('checks', [])
            valid = (report.get('status') == 'pass' and len(views) == 2 and
                     [v.get('viewport') for v in views] == [[1280, 800], [390, 844]] and
                     all([s.get('state') for s in v.get('states', [])] == ['checked', 'changed', 'restored'] and
                         all(s.get('ok') is True for s in v['states']) for v in views))
            sys.exit(0 if valid else 1)
        except (OSError, ValueError): sys.exit(1)
    else: sys.exit('usage: probe.py run|skip|check')
