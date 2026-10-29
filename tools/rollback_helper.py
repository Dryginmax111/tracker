#!/usr/bin/env python3
r"""rollback_helper.py - read .patches_applied.json for rollback.bat.

Commands:
    (no args)       - list: N|id|applied_at|description  (one per line)
    --count         - print number of applied patches
    --get-id N      - print patch id for number N
    --list-reversed - print ids newest-first (for rollback ALL)

Exit codes:
    0 - OK
    1 - general error
    2 - journal not found
    3 - journal corrupted
    4 - N out of range
    5 - bad N
"""
import json
import sys
from pathlib import Path


def _find_journal():
    here = Path(__file__).parent.resolve()
    probes = [
        here.parent / 'core' / '.patches_applied.json',
        here.parent / 'tools' / '.patches_applied.json',
        here / '.patches_applied.json',
        here.parent / '.patches_applied.json',
    ]
    for p in probes:
        if p.exists():
            return p
    return None


def main():
    jp = _find_journal()
    if jp is None:
        print('NO_JOURNAL')
        return 2
    try:
        data = json.loads(jp.read_text(encoding='utf-8-sig'))
    except Exception as e:
        print(f'BAD_JOURNAL|{e}')
        return 3
    if not isinstance(data, dict):
        print('BAD_JOURNAL|not a dict')
        return 3
    if not data:
        print('EMPTY')
        return 0

    args = sys.argv[1:]

    if not args:
        for i, (pid, info) in enumerate(data.items(), 1):
            info = info or {}
            ts = str(info.get('applied_at') or '?')
            desc = str(info.get('description') or '').replace('|', '/')[:60]
            print(f'{i}|{pid}|{ts}|{desc}')
        return 0

    if args[0] == '--count':
        print(len(data))
        return 0

    if args[0] == '--get-id' and len(args) >= 2:
        try:
            n = int(args[1])
        except ValueError:
            print('BAD_NUMBER')
            return 5
        keys = list(data.keys())
        if 1 <= n <= len(keys):
            print(keys[n - 1])
            return 0
        print('OUT_OF_RANGE')
        return 4

    if args[0] == '--list-reversed':
        for k in reversed(list(data.keys())):
            print(k)
        return 0

    print('USAGE')
    return 1


if __name__ == '__main__':
    sys.exit(main())
