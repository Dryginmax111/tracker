#!/usr/bin/env python3
r"""build_bundle.py — объединяет проверенные патчи в один bundle.json.

Алгоритм:
  1. Находит patcher.py (в tools/../core/, или в текущей папке)
  2. Сортирует патчи по target_version + requires граф
  3. Применяет каждый патч в dry-режиме (overlay VFS, chained)
     → видит каждую операцию (replace/regex/write/...), как patcher.py
  4. Если ВСЕ патчи прошли → собирает операции в один bundle
  5. Проверяет bundle в dry-режиме (reset VFS, применить как один патч)
  6. Пишет bundle.json

Использование:
    python tools/build_bundle.py <папка_с_патчами>
    python tools/build_bundle.py <папка> -o my_bundle.json
    python tools/build_bundle.py <папка> --id bundle-v1.0.5
    python tools/build_bundle.py <папка> --dry   # только проверить, не писать

Коды возврата:
    0 — bundle собран
    1 — какой-то патч не прошёл dry-run
    2 — bundle не прошёл финальную проверку (баг patcher)
"""
import argparse
import json
import sys
from pathlib import Path

_here = Path(__file__).parent.resolve()

# Найти patcher.py — поднимаемся вверх, пока не найдём core/patcher.py
_patcher_dir = None
_probe = _here
for _ in range(5):
    if (_probe / 'patcher.py').exists():
        _patcher_dir = _probe
        break
    if (_probe / 'core' / 'patcher.py').exists():
        _patcher_dir = _probe / 'core'
        break
    _probe = _probe.parent

if _patcher_dir is None:
    print('! patcher.py не найден. Искал:')
    print(f'  {_here}/patcher.py')
    print(f'  {_here}/core/patcher.py')
    print(f'  {_here.parent}/core/patcher.py')
    sys.exit(1)

sys.path.insert(0, str(_patcher_dir))
try:
    import patcher as _P
    from patcher import _sort_patch_files, apply_patch, _vfs_reset
except Exception as e:
    print(f'! Не удалось импортировать patcher.py: {e}')
    sys.exit(1)

# BASE = каталог, где лежит patcher.py.
# Все патчи используют пути относительно него: "app.py", "auth.py", "static/tracker.js".
# У вас patcher.py в core/ — значит BASE = core/, и "app.py" ищется в core/app.py.
BASE = _patcher_dir


def main():
    ap = argparse.ArgumentParser(description='Bundle verified patches into one JSON.')
    ap.add_argument('folder', help='папка с *.json патчами')
    ap.add_argument('-o', '--output', default=None, help='имя выходного bundle.json')
    ap.add_argument('--id', default=None, help='id для bundle')
    ap.add_argument('--dry', action='store_true', help='только проверить, не писать')
    args = ap.parse_args()

    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        print(f'! Не папка: {folder}')
        return 1

    patch_files = sorted(folder.glob('*.json'))
    if not patch_files:
        print(f'! В {folder} нет *.json')
        return 1

    print(f'BASE:   {BASE}')
    print(f'PATTER: {_patcher_dir}')
    print(f'Патчей: {len(patch_files)}')
    print()

    ordered = _sort_patch_files(patch_files)
    print(f'Порядок применения ({len(ordered)}):')
    for f in ordered:
        try:
            _p = json.loads(f.read_text(encoding='utf-8-sig'))
            _pid = _p.get('id', f.stem)
            _ver = _p.get('target_version', '?')
            _ops = len(_p.get('operations') or _p.get('ops') or [])
            print(f'  · {_pid}  v{_ver}  ({_ops} ops)')
        except Exception as e:
            print(f'  · {f.name}  ! ошибка чтения: {e}')
    print()

    # Применить каждый патч в dry (chained)
    _vfs_reset()
    applied = []
    total_ops = 0
    for i, f in enumerate(ordered, 1):
        try:
            patch = json.loads(f.read_text(encoding='utf-8-sig'))
        except Exception as e:
            print(f'\n! [{i}/{len(ordered)}] {f.name}: не JSON: {e}')
            return 1
        pid = patch.get('id') or f.stem
        n_ops = len(patch.get('operations') or patch.get('ops') or [])
        print(f'\n=== [{i}/{len(ordered)}] {pid} ({n_ops} ops, {f.name}) ===')
        ok, _ = apply_patch(patch, BASE, dry=True, no_backup=True)
        if not ok:
            print(f'\n! ПРОВАЛ на патче «{pid}» ({f.name})')
            print(f'! Bundle не собран. Исправьте патч и перезапустите.')
            return 1
        applied.append(patch)
        total_ops += n_ops

    # Собрать операции
    all_ops = []
    for p in applied:
        all_ops.extend(p.get('operations') or p.get('ops') or [])

    versions = [p.get('target_version') for p in applied if p.get('target_version')]
    max_ver = max(versions, key=_P._ver_tuple) if versions else '1.0.0'

    bundle_id = args.id or f'bundle-{len(applied)}patches-v{max_ver}'
    bundle = {
        'id': bundle_id,
        'description': f'Bundle from {len(applied)} verified patches: '
                       + ', '.join(p.get('id') for p in applied),
        'target_version': max_ver,
        'requires': [],
        '_applied_after': [p.get('id') for p in applied],
        'operations': all_ops,
    }

    # Финальная проверка: bundle как единый патч
    print(f'\n=== ВЕРИФИКАЦИЯ BUNDLE ({len(all_ops)} ops) ===')
    _vfs_reset()
    ok, _ = apply_patch(bundle, BASE, dry=True, no_backup=True)
    if not ok:
        print(f'\n! Bundle сам по себе не применяется. Это баг patcher.py.')
        print(f'! Патчи по отдельности прошли, но merged bundle — нет.')
        return 2

    print(f'\nOK Bundle прошёл верификацию. Всего операций: {len(all_ops)}')
    print(f'   Патчей объединено: {len(applied)}')
    print(f'   Целевая версия:    {max_ver}')

    if args.dry:
        print('\n(dry) bundle не записан')
        return 0

    out = Path(args.output) if args.output else BASE / f'{bundle_id}.json'
    if not out.is_absolute():
        out = BASE / out
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\nOK Записан: {out}')
    print(f'   Размер: {out.stat().st_size:,} байт'.replace(',', ' '))
    return 0


if __name__ == '__main__':
    sys.exit(main())
