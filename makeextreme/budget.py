"""Optional admission check for declared budgets; not a billing monitor."""
import argparse
import json
from pathlib import Path


def integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f'{name} must be a nonnegative integer')
    return value


def assess(plan):
    fields = {'version', 'attempts_used', 'max_attempts', 'retry_reserve', 'resources'}
    if not isinstance(plan, dict) or set(plan) != fields or type(plan['version']) is not int or plan['version'] != 1:
        raise ValueError('expected budget plan version 1 and exact fields')
    used = integer(plan['attempts_used'], 'attempts_used')
    maximum = integer(plan['max_attempts'], 'max_attempts')
    retries = integer(plan['retry_reserve'], 'retry_reserve')
    resources = plan['resources']
    if not isinstance(resources, dict) or not resources:
        raise ValueError('resources must be a nonempty mapping')
    reasons, result = [], {}
    if used + 1 + retries > maximum:
        reasons.append('attempt_limit')
    for name, values in resources.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError('resource names must be nonempty')
        if not isinstance(values, dict) or set(values) != {'remaining', 'attempt', 'recovery', 'verification'}:
            raise ValueError(f'{name}: expected remaining, attempt, recovery, verification')
        for key, value in values.items():
            if value is not None:
                integer(value, name + '.' + key)
        if any(value is None for value in values.values()):
            reasons.append(f'{name}:unknown')
            result[name] = {'required': None, 'headroom': None}
            continue
        required = values['attempt'] * (1 + retries) + values['recovery'] + values['verification']
        headroom = values['remaining'] - required
        result[name] = {'required': required, 'headroom': headroom}
        if headroom < 0:
            reasons.append(f'{name}:insufficient')
    return {'admit': not reasons, 'reasons': reasons, 'resources': result,
            'scope': 'declared estimates only; no approval or spending enforcement'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    args = parser.parse_args()
    try:
        decision = assess(json.loads(args.plan.read_text()))
    except (OSError, ValueError) as exc:
        parser.exit(64, f'budget plan refused: {exc}\n')
    print(json.dumps(decision, sort_keys=True))
    return 0 if decision['admit'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
