#!/usr/bin/env python3
"""
fix_overload_days.py — пропорционально ужимает дни, где сумма часов
по одному сотруднику за одну дату превышает 8.

Использование:
    python scripts/fix_overload_days.py --dry      # только показать
    python scripts/fix_overload_days.py --apply    # применить

Отчёт пишется в scripts/fix_overload_report.txt.
"""
import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).parent.parent
LIMIT = 8.0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--limit', type=float, default=LIMIT)
    args = ap.parse_args()
    if not (args.dry or args.apply):
        print('Укажите --dry или --apply')
        return 1

    cfg = json.loads((BASE / 'config.json').read_text(encoding='utf-8'))
    db_path = cfg.get('db_path') or 'task_tracker.db'
    p = Path(db_path)
    if not p.is_absolute():
        p = BASE / p
    if not p.exists():
        print(f'! БД не найдена: {p}')
        return 1

    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        'SELECT id, employee_id, task_id, date, hours, comment FROM work_logs '
        'ORDER BY employee_id, date, id'
    ).fetchall()

    groups = defaultdict(list)
    for r in rows:
        groups[(r['employee_id'], r['date'])].append(r)

    report = []
    total_fixed = 0
    affected_entries = 0

    for (emp, dk), entries in groups.items():
        s = round(sum(float(e['hours'] or 0) for e in entries), 4)
        if s <= args.limit:
            continue
        # Пропорционально уменьшаем до limit, округляя до 0.25
        new_hours = []
        acc = 0.0
        for i, e in enumerate(entries):
            if i == len(entries) - 1:
                h = round((args.limit - acc) * 4) / 4
            else:
                h = round((float(e['hours'] or 0) / s * args.limit) * 4) / 4
            if h < 0.25:
                h = 0.25
            new_hours.append(h)
            acc += h
        # подгонка последней, чтобы точно сумма = limit
        diff = round(args.limit - sum(new_hours), 4)
        if abs(diff) >= 0.25:
            idx = max(range(len(new_hours)), key=lambda k: new_hours[k])
            new_hours[idx] = round((new_hours[idx] + diff) * 4) / 4

        report.append(
            f'{emp} | {dk} | было {s} ч ({len(entries)} записей) -> стало '
            + str(round(sum(new_hours), 2)) + ' ч'
        )
        total_fixed += 1
        affected_entries += len(entries)

        if args.apply:
            for e, h in zip(entries, new_hours):
                conn.execute('UPDATE work_logs SET hours=? WHERE id=?', (h, e['id']))
            conn.commit()

    rep_path = Path(__file__).parent / 'fix_overload_report.txt'
    rep_path.write_text('\n'.join(report) + '\n', encoding='utf-8')

    print(f'Дней с перегрузом: {total_fixed}')
    print(f'Записей затронуто: {affected_entries}')
    print(f'Отчёт: {rep_path}')
    print('Режим: ' + ('APPLY' if args.apply else 'DRY (ничего не изменено)'))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())