"""Call FlowLore's existing scorer and package its one-case result."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def score():
    cfg = load('config.json')
    # The native CLI prints JSON even for a wrong answer and then exits 0. Its
    # process exit code is necessary for infrastructure errors, not sufficient
    # for acceptance. Truncate stale output even when the scorer cannot run.
    with open('score.json', 'w', encoding='utf-8') as output:
        return subprocess.run([sys.executable, cfg['sources']['scorer'], cfg['case'],
                               'reply.txt', '--longhaul', cfg['longhaul']],
                              stdout=output).returncode


def checked_score():
    result = load('score.json')
    if not isinstance(result, dict) or type(result.get('score')) is not int or result['score'] != 1 \
            or result.get('failure') is not None or not isinstance(result.get('expected'), dict) \
            or not isinstance(result.get('got'), dict) or not isinstance(result.get('detail'), str):
        raise ValueError('native scorer did not accept this reply')
    return result


def report():
    cfg = load('config.json')
    return {'case': cfg['case'], 'reply_sha256': sha('reply.txt'),
            'source_sha256': {name: sha(path) for name, path in cfg['sources'].items()},
            'evaluation': checked_score()}


def main(action, config_hash):
    # Source paths are also hard-bound in stages.json's deps. Refuse a config
    # edit that could otherwise point at an untracked checker on the next run.
    if action == 'score':
        Path('score.json').write_text('', encoding='utf-8')
    if sha('config.json') != config_hash:
        raise ValueError('config changed; create a new task')
    if action == 'score':
        return score()
    if action == 'check-score':
        checked_score()
        return 0
    if action == 'report':
        Path('accepted.json').write_text(json.dumps(report(), indent=2) + '\n', encoding='utf-8')
        return 0
    if action == 'check-report':
        if load('accepted.json') != report():
            raise ValueError('accepted record does not match the current inputs and result')
        return 0
    raise ValueError(f'unknown action: {action}')


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1], sys.argv[2]))
    except (IndexError, KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'pipeline refused: {exc}', file=sys.stderr)
        sys.exit(1)
