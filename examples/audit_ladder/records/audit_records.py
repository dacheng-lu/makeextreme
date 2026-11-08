#!/usr/bin/env python3
"""Validate local audit records; no model calls or target-code execution.

This is a local format inspired by Cloudflare's verdict/coverage discipline,
not an implementation of its report-schema.json or an independent auditor.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def evidence(root, item):
    require(isinstance(item, dict) and set(item) == {'path', 'sha256'}, 'bad evidence reference')
    path = Path(item['path'])
    require(not path.is_absolute() and '..' not in path.parts, 'evidence must be relative')
    resolved = (root / path).resolve()
    require(resolved.is_relative_to(root.resolve()) and resolved.is_file(), 'missing or escaped evidence')
    require(re.fullmatch(r'[0-9a-f]{64}', item['sha256']) is not None, 'bad evidence hash')
    require(digest(resolved) == item['sha256'], 'stale evidence')


def validate(root, records_name='records.json'):
    scope = read(root / 'scope.json')
    records = read(root / records_name)
    require(set(scope) == {'base', 'head'}, 'bad scope fields')
    require(all(isinstance(v, str) and re.fullmatch(r'[0-9a-f]{40}', v) for v in scope.values()), 'scope needs full commits')
    require(set(records) == {'version', 'scope', 'coverage', 'findings'}, 'bad record fields')
    require(type(records['version']) is int and records['version'] == 1, 'unsupported version')
    require(records['scope'] == scope, 'stale source scope')
    coverage = records['coverage']
    require(isinstance(coverage, list) and coverage, 'coverage must be nonempty')
    units = set()
    for unit in coverage:
        require(set(unit) == {'id', 'status', 'evidence'}, 'bad coverage fields')
        require(isinstance(unit['id'], str) and unit['id'].strip() and unit['id'] not in units, 'duplicate/empty coverage id')
        units.add(unit['id'])
        require(unit['status'] in ('checked', 'open'), 'bad coverage status')
        require(isinstance(unit['evidence'], list), 'bad coverage evidence')
        require(unit['status'] != 'checked' or unit['evidence'], 'checked unit needs evidence')
        for ref in unit['evidence']:
            evidence(root, ref)
    require(isinstance(records['findings'], list), 'findings must be a list')
    ids = set()
    for finding in records['findings']:
        require(set(finding) == {'id', 'unit', 'verdict', 'author', 'reviewer', 'reason', 'severity', 'evidence'}, 'bad finding fields')
        require(isinstance(finding['id'], str) and finding['id'].strip() and finding['id'] not in ids, 'duplicate/empty finding id')
        ids.add(finding['id'])
        require(finding['unit'] in units, 'unknown coverage unit')
        require(finding['verdict'] in ('confirmed', 'needs_validation', 'rejected'), 'bad verdict')
        require(all(isinstance(finding[k], str) and finding[k].strip() for k in ('author', 'reason')), 'missing author/reason')
        require(isinstance(finding['evidence'], list), 'bad finding evidence')
        if finding['verdict'] == 'needs_validation':
            require(finding['severity'] is None, 'unvalidated finding cannot have severity')
        else:
            require(isinstance(finding['reviewer'], str) and finding['reviewer'].strip() and finding['reviewer'] != finding['author'], 'separate reviewer required')
            require(finding['evidence'], 'resolved finding needs evidence')
            require(finding['severity'] in ('critical', 'high', 'medium', 'low') if finding['verdict'] == 'confirmed' else finding['severity'] is None, 'bad severity')
        for ref in finding['evidence']:
            evidence(root, ref)
    return records


def report(records):
    counts = {v: sum(f['verdict'] == v for f in records['findings']) for v in ('confirmed', 'needs_validation', 'rejected')}
    opened = sum(u['status'] == 'open' for u in records['coverage'])
    return ('# Audit record summary\n\nSource: ' + records['scope']['head'] + '\n\n'
            + '\n'.join(f'{k}: {v}' for k, v in counts.items()) + f'\nopen coverage: {opened}\n\n'
            + 'Record consistency only; reviewer identities and vulnerability claims are not authenticated.\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['snapshot', 'check-snapshot', 'report', 'check-report'])
    args = parser.parse_args()
    root = Path.cwd()
    try:
        name = 'records.json' if args.action == 'snapshot' else 'validated.json'
        records = validate(root, name)
        if args.action == 'snapshot':
            (root / 'validated.json').write_text(json.dumps(records, indent=2) + '\n')
        elif args.action == 'report':
            (root / 'report.md').write_text(report(records))
        elif args.action == 'check-report':
            require((root / 'report.md').read_text() == report(records), 'report differs from records')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f'audit records refused: {exc}\n')


if __name__ == '__main__':
    main()
