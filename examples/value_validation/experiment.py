"""Offline, synthetic value-validation example. No network or real customer data."""
import json
import sys
from pathlib import Path


def summarize():
    offer = json.loads(Path('offer.json').read_text())
    observations = json.loads(Path('observations.json').read_text())
    assert offer['revision'] and observations['offer_revision'] == offer['revision'], 'stale offer revision'
    rows = observations['observations']
    assert rows and all(r['kind'] == 'synthetic' and r['outcome'] in ('paid', 'declined', 'unknown') for r in rows)
    assert all(isinstance(r['minutes'], int) and not isinstance(r['minutes'], bool) and r['minutes'] >= 0 for r in rows)
    report = {'label': 'SYNTHETIC — not evidence of customer demand', 'offer_revision': offer['revision'],
              'sample': len(rows), 'paid': sum(r['outcome'] == 'paid' for r in rows),
              'unknown': sum(r['outcome'] == 'unknown' for r in rows),
              'human_minutes': sum(r['minutes'] for r in rows), 'hypothesis': 'inconclusive'}
    Path('report.json').write_text(json.dumps(report, indent=2) + '\n')


def check():
    r = json.loads(Path('report.json').read_text())
    assert r['label'].startswith('SYNTHETIC') and r['hypothesis'] == 'inconclusive'
    assert r['offer_revision'] == json.loads(Path('offer.json').read_text())['revision']
    assert r['sample'] > 0 and 0 <= r['paid'] + r['unknown'] <= r['sample']


if __name__ == '__main__':
    {'summarize': summarize, 'check': check}[sys.argv[1]]()
