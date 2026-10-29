#!/usr/bin/env python3
r"""health_check.py — диагностика проекта (16 проверок).

Запуск:
    runtime\embedded\python313\python.exe health_check.py
"""
import ast
import json
import re
import sys
from pathlib import Path

_here = Path(__file__).parent.resolve()
BASE = None
_probe = _here
for _ in range(5):
    if (_probe / 'core').is_dir():
        BASE = _probe
        break
    _probe = _probe.parent
if BASE is None:
    print(f'! Не найден каталог core/ рядом с {_here} или выше')
    print(f'  Проверено: {_here}, {_here.parent}, {_here.parent.parent}')
    sys.exit(1)
CORE = BASE / 'core'


def _check(name, fn):
    try:
        ok, msg = fn()
    except Exception as e:
        print(f'[ERROR] {name}: {e}')
        return False
    print(f'[{"OK" if ok else "FAIL"}] {name}: {msg}')
    return ok


def c_pycompile():
    fails = []
    files = list(CORE.glob('*.py')) + list((CORE / 'plugins').glob('*.py'))
    for f in files:
        try:
            ast.parse(f.read_text(encoding='utf-8'))
        except SyntaxError as e:
            fails.append(f'{f.name}:{e.lineno}: {e.msg}')
    if fails:
        return False, '; '.join(fails[:3])
    return True, f'{len(files)} файлов OK'


def c_weekly_import():
    sys.path.insert(0, str(CORE))
    if 'plugins.weekly_report' in sys.modules:
        del sys.modules['plugins.weekly_report']
    try:
        import plugins.weekly_report  # noqa: F401
        return True, 'import OK'
    except Exception as e:
        return False, str(e)


def c_wr_content():
    p = CORE / 'plugins' / 'weekly_report.py'
    if not p.exists():
        return False, 'файла нет'
    txt = p.read_text(encoding='utf-8')
    if txt.strip() == 'PLACEHOLDER_PY':
        return False, 'PLACEHOLDER_PY (не перезаписан)'
    if len(txt) < 5000:
        return False, f'слишком маленький ({len(txt)} байт)'
    return True, f'{len(txt)} байт'


def c_wr_cfg():
    p = CORE / 'plugins' / 'weekly_report.json'
    if not p.exists():
        return False, 'не создан'
    try:
        cfg = json.loads(p.read_text(encoding='utf-8'))
        return True, f'enabled={cfg.get("enabled")}'
    except Exception as e:
        return False, str(e)


def c_wr_script():
    for hp in (CORE / 'tamplates' / 'tracker.html',
               CORE / 'templates' / 'tracker.html'):
        if not hp.exists():
            continue
        txt = hp.read_text(encoding='utf-8')
        if 'weekly_report.js' in txt:
            return True, f'{hp.parent.name}/tracker.html'
    return False, 'нет <script src="/plugins-assets/weekly_report.js"> в tracker.html'


def c_tracker_js():
    p = CORE / 'static' / 'tracker.js'
    if not p.exists():
        return True, 'нет файла'
    hits = len(re.findall(r'/plugins/weekly_report/', p.read_text(encoding='utf-8')))
    if hits == 0:
        return True, 'нет захардкоженных ссылок'
    return False, f'{hits} ссылок (дублирует плагин)'


def c_secret_key():
    try:
        cfg = json.loads((CORE / 'config.json').read_text(encoding='utf-8'))
        sk = (cfg.get('secret_key') or '').strip()
        if not sk or sk == '...':
            return False, 'placeholder "..." — при старте будет генерироваться новый ключ'
        return True, f'OK ({len(sk)} символов)'
    except Exception as e:
        return False, str(e)


def c_version():
    try:
        v = json.loads((CORE / 'client_version.json').read_text(encoding='utf-8'))
        return True, v.get('version', '?')
    except Exception as e:
        return False, str(e)


def c_patches():
    p = CORE / '.patches_applied.json'
    if not p.exists():
        return True, '0 (нет журнала)'
    try:
        j = json.loads(p.read_text(encoding='utf-8'))
        keys = sorted(j.keys())
        return True, f'{len(j)}: {", ".join(keys[-3:])}'
    except Exception as e:
        return False, str(e)


def c_openpyxl():
    try:
        import openpyxl
        return True, openpyxl.__version__
    except ImportError:
        return False, 'не установлен'


def c_templates():
    has = (CORE / 'templates').is_dir()
    has2 = (CORE / 'tamplates').is_dir()
    if has and has2:
        return False, 'ОБА каталога: templates/ и tamplates/ — правки в tamplates/ ИГНОРИРУЮТСЯ'
    if has:
        return True, 'templates/'
    if has2:
        return True, 'tamplates/ (без s, но работает)'
    return False, 'нет каталогов шаблонов'


def c_fix_log_id():
    p = CORE / 'app.py'
    if not p.exists():
        return False, 'нет app.py'
    if '_created_flag = isinstance(created, int)' in p.read_text(encoding='utf-8'):
        return True, 'v1.0.2 фикс есть'
    return False, 'старый код (log_id=created) — pull_task_summary не пересчитывает'


def c_fix_heatmap():
    p = CORE / 'app.py'
    if not p.exists():
        return False, 'нет app.py'
    if '_ifu_hm' in p.read_text(encoding='utf-8'):
        return True, 'v1.0.2 фикс есть'
    return False, 'нет фильтра будущих отметок в api_heatmap'


def c_fix_parse_ym():
    p = CORE / 'app.py'
    if not p.exists():
        return False, 'нет app.py'
    if 'year out of range' in p.read_text(encoding='utf-8'):
        return True, 'v1.0.2 фикс есть'
    return False, 'нет clamp в _parse_ym'


def c_fix_csrf():
    for lp in (CORE / 'tamplates' / 'login.html',
               CORE / 'templates' / 'login.html'):
        if not lp.exists():
            continue
        if 'name="csrf_token"' in lp.read_text(encoding='utf-8'):
            return True, 'есть'
    return False, 'нет csrf_token в login.html'


def c_fix_session_perm():
    p = CORE / 'auth.py'
    if not p.exists():
        return False, 'нет auth.py'
    if 'session.permanent = True' in p.read_text(encoding='utf-8'):
        return True, 'есть'
    return False, 'нет session.permanent=True — сессия умирает при закрытии браузера'


def main():
    print('=' * 62)
    print(' health_check.py — диагностика проекта')
    print(f' {BASE}')
    print('=' * 62)
    print()
    checks = [
        ('Python-компиляция всех .py',        c_pycompile),
        ('weekly_report.py импортируется',     c_weekly_import),
        ('weekly_report.py содержимое',        c_wr_content),
        ('weekly_report.json',                 c_wr_cfg),
        ('<script> в tracker.html',            c_wr_script),
        ('tracker.js без захардкоженных',      c_tracker_js),
        ('secret_key в config.json',           c_secret_key),
        ('client_version.json',                c_version),
        ('Применённые патчи',                  c_patches),
        ('openpyxl',                            c_openpyxl),
        ('Каталоги шаблонов',                  c_templates),
        ('Fix v1.0.2: log_id (pull_task_summary)', c_fix_log_id),
        ('Fix v1.0.2: heatmap ignore_future',  c_fix_heatmap),
        ('Fix v1.0.2: _parse_ym clamp',        c_fix_parse_ym),
        ('Fix v1.0.2: CSRF в login',           c_fix_csrf),
        ('Fix v1.0.2: session.permanent',      c_fix_session_perm),
    ]
    ok_n = 0
    fail_n = 0
    for name, fn in checks:
        if _check(name, fn):
            ok_n += 1
        else:
            fail_n += 1
    print()
    print(f'Итого: {ok_n} OK, {fail_n} FAIL')
    if fail_n == 0:
        print('🎉 Всё в порядке — можно продолжать работу')
        return 0
    print('⚠ См. FAIL выше — что требует внимания')
    return 1


if __name__ == '__main__':
    sys.exit(main())
