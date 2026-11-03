"""Create the demonstration task in a new directory."""
import json
import shutil
import sys
from pathlib import Path

target = Path(sys.argv[1]).resolve()
target.mkdir(parents=True, exist_ok=False)
shutil.copy(Path(__file__).with_name('experiment.py'), target / 'experiment.py')
(target / 'offer.json').write_text(json.dumps({'revision': 'demo-v1', 'audience': 'synthetic demo'}) + '\n')
(target / 'observations.json').write_text(json.dumps({'offer_revision': 'demo-v1', 'observations': [
    {'kind': 'synthetic', 'outcome': 'declined', 'minutes': 12},
    {'kind': 'synthetic', 'outcome': 'unknown', 'minutes': 8}]}) + '\n')
(target / 'stages.json').write_text(json.dumps([{'id': 'summarize',
    'run': 'python3 experiment.py summarize', 'check': 'python3 experiment.py check',
    'deps': ['offer.json', 'observations.json', 'experiment.py'], 'outputs': ['report.json']}], indent=2) + '\n')
print(target)
