#!/usr/bin/env python3
"""reset_version.py — разовый сброс цепочки версий в 1.0.0.

Делает три вещи:
  1. Копирует текущий .patches_applied.json в .patches_applied.archive-<ts>.json
  2. Пишет пустой .patches_applied.json ({}).
  3. Пишет client_version.json с version=1.0.0, last_patch_id='reset'.

Запускать ОДИН раз, до применения новых патчей v1.0.1+.
После этого старые патчи в net_update.share_path надо УБРАТЬ — иначе
updater посчитает их «неприменёнными» и попробует накатить заново.
"""
import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.resolve()
JOURNAL = BASE / '.patches_applied.json'
VERSION = BASE / 'client_version.json'
STALE = BASE / 'patches_applied.json'  # опечатка из старого архива — не нужен


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--to', default='1.0.0')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--force', action='store_true',
                    help='перезаписать журнал, даже если он не пуст')
    args = ap.parse_args()

    old = {}
    if JOURNAL.exists():
        try:
            old = json.loads(JOURNAL.read_text(encoding='utf-8'))
        except Exception:
            old = {}

    if old and not args.force:
        print(f'Журнал НЕ пуст ({len(old)} записей). '
              f'Если уверены — запустите с --force')
        return 2

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    archive = BASE / f'.patches_applied.archive-{ts}.json'

    if args.dry:
        print(f'[dry] archive → {archive.name} ({len(old)} записей)')
        print(f'[dry] journal → {{}}')
        print(f'[dry] version → {args.to}')
        return 0

    if JOURNAL.exists():
        shutil.copy2(JOURNAL, archive)
        print(f'✓ Архив журнала: {archive.name}')

    JOURNAL.write_text('{}', encoding='utf-8')
    print(f'✓ Журнал очищен: {JOURNAL.name}')

    VERSION.write_text(json.dumps({
        'version': args.to,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'last_patch_id': 'reset',
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'✓ Версия: {args.to}')

    if STALE.exists():
        print(f'⚠ Внимание: {STALE.name} в корне — это опечатка старого '
              f'архива, patcher его не читает. Можно удалить.')

    print()
    print('Далее:')
    print('  1) Очистить net_update.share_path от патчей v1.x.x')
    print('     (или сменить share_path на свежую пустую папку).')
    print('  2) Положить туда патчи v1.0.1 … v1.0.6 из этого комплекта.')
    print('  3) /plugins/updater/ → Проверить → Применить.')
    print('  4) /api/settings/restart.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())