"""Verify the two-step local demo's final state and journal."""
import json
import sys
from pathlib import Path

task = Path(sys.argv[1])
assert (task / 'report.txt').read_bytes() == (task / 'seed.txt').read_bytes()
events = [json.loads(line) for line in (task / 'journal.jsonl').read_text().splitlines()]
starts = [event['stage'] for event in events if event['ev'] == 'start']
skips = [event['stage'] for event in events if event['ev'] == 'skip']
assert starts.count('prepare') == 1 and starts.count('render') == 2, starts
assert 'prepare' in skips, skips
print('Verified one prepare, two render attempts, and the checked report.')
