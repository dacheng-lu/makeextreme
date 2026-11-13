#!/usr/bin/env python3
"""Create a local task that scores one saved reply with FlowLore's scorer."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', type=Path, help='new task directory')
    parser.add_argument('--flowlore', type=Path, required=True, help='FlowLore checkout')
    parser.add_argument('--longhaul', type=Path, required=True, help='Longhaul checkout')
    parser.add_argument('--case', required=True, help='FlowLore local-model-baseline case ID')
    parser.add_argument('--reply', type=Path, required=True, help='saved model reply (UTF-8)')
    args = parser.parse_args()
    flowlore, longhaul = args.flowlore.resolve(), args.longhaul.resolve()
    sources = {
        'scorer': flowlore / 'examples/local-model-baseline/scorer.py',
        'scenarios': flowlore / 'examples/local-model-baseline/scenarios.py',
        'digest': flowlore / 'examples/release-digest/digest.py',
        'checkpoint': longhaul / 'scripts/checkpoint.py',
        'secret_scan': longhaul / 'scripts/secret_scan.py',
    }
    for path in [*sources.values(), args.reply]:
        if not path.is_file():
            parser.error(f'file not found: {path}')
    target = args.task.resolve()
    target.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(args.reply, target / 'reply.txt')
    shutil.copyfile(Path(__file__).with_name('pipeline.py'), target / 'pipeline.py')
    config = {'case': args.case, 'longhaul': str(longhaul),
              'sources': {name: str(path) for name, path in sources.items()}}
    config_text = json.dumps(config, indent=2) + '\n'
    (target / 'config.json').write_text(config_text)
    config_hash = hashlib.sha256(config_text.encode()).hexdigest()
    py = shlex.quote(sys.executable)
    command = lambda action: f'{py} pipeline.py {action} {config_hash}'
    source_deps = list(config['sources'].values())
    stages = [
        {'id': 'score', 'run': command('score'), 'check': command('check-score'),
         'deps': ['reply.txt', 'config.json', 'pipeline.py', *source_deps],
         'outputs': ['score.json'], 'timeout': 240},
        {'id': 'report', 'run': command('report'), 'check': command('check-report'),
         'deps': ['score.json', 'reply.txt', 'config.json', 'pipeline.py', *source_deps],
         'outputs': ['accepted.json'], 'timeout': 30},
    ]
    (target / 'stages.json').write_text(json.dumps(stages, indent=2) + '\n')
    print(target)


if __name__ == '__main__':
    main()
