#!/usr/bin/env python3
"""Exhaustive paired toy traces, not a benchmark of agents or Kelly sizing."""
import itertools
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from makeextreme.budget import assess


def simulate(outcomes, guarded, budget=10, attempt=2, verification=3):
    remaining, calls, ready, spent = budget, 0, False, 0
    for outcome in outcomes:
        if guarded:
            plan = {'version': 1, 'attempts_used': calls, 'max_attempts': len(outcomes),
                    'retry_reserve': 0, 'resources': {'units': {'remaining': remaining,
                    'attempt': attempt, 'recovery': 0, 'verification': verification}}}
            if not assess(plan)['admit']:
                break
        elif remaining < attempt:
            break
        remaining -= attempt
        spent += attempt
        calls += 1
        if outcome:
            ready = True
            break
    complete = ready and remaining >= verification
    if complete:
        remaining -= verification
        spent += verification
    return {'complete': complete, 'spent': spent, 'calls': calls,
            'unverified_output': ready and not complete, 'remaining': remaining}


def compare():
    # All 16 traces have equal weight. Includes four consecutive failures and
    # late success. Correlated deployments are represented separately below.
    traces = list(itertools.product([False, True], repeat=4))
    results = {}
    for name, guarded in [('baseline', False), ('reserve', True)]:
        rows = [simulate(trace, guarded) for trace in traces]
        results[name] = {'completed': sum(r['complete'] for r in rows), 'traces': len(rows),
                         'total_spent': sum(r['spent'] for r in rows),
                         'unverified_outputs': sum(r['unverified_output'] for r in rows),
                         'all_fail': simulate([False] * 4, guarded)}
    results['correlated_failure'] = {name: [simulate([False]*4, guarded) for _ in range(3)]
                                     for name, guarded in [('baseline', False), ('reserve', True)]}
    return results


if __name__ == '__main__':
    print(json.dumps(compare(), indent=2, sort_keys=True))
