"""Standalone launcher трекера задач."""
import json
import sys
import webbrowser
import threading
from pathlib import Path

# --- FIX: embedded Python не добавляет папку скрипта в sys.path ---
_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def _ensure_site_packages():
    """FIX v1.1.9.1: самовосстановление окружения embedded Python.

    Если запуск идёт из embedded-интерпретатора (рядом лежит pythonXXX._pth),
    а Flask/openpyxl не импортируются — молча распаковываем wheel'ы из
    tools/wheels в Lib/site-packages вместо бесконечного рестарта сервера.
    Для обычного (системного) Python функция ничего не делает.
    """
    exe_dir = Path(sys.executable).resolve().parent
    if not any(exe_dir.glob('*._pth')):
        return  # не embedded-среда, трогать нечего
    try:
        import flask  # noqa: F401
        import openpyxl  # noqa: F401
        return
    except ImportError:
        pass
    wheels_dir = None
    for cand in (exe_dir.parents[2] / 'tools' / 'wheels',   # runtime/embedded/<py>/ -> root/tools/wheels
                 _HERE.parent / 'tools' / 'wheels'):         # core/../tools/wheels
        if cand.is_dir() and any(cand.glob('*.whl')):
            wheels_dir = cand
            break
    if wheels_dir is None:
        print('[!] Не найдены библиотеки (flask/openpyxl) и папка tools\\wheels с wheel-архивами.')
        print('    Запустите tools\\install_offline.bat или используйте START_wheels.bat')
        return
    site_pkgs = exe_dir / 'Lib' / 'site-packages'
    site_pkgs.mkdir(parents=True, exist_ok=True)
    if str(site_pkgs) not in sys.path:
        sys.path.append(str(site_pkgs))
    print(f'[setup] Библиотеки не найдены — распаковываем wheel-пакеты в {site_pkgs} ...')
    import zipfile
    for whl in sorted(wheels_dir.glob('*.whl')):
        tag = whl.stem.split('-')[-1]
        cur_tag = f'cp{sys.version_info.major}{sys.version_info.minor}-cp{sys.version_info.major}{sys.version_info.minor}'
        if 'cp3' in tag and cur_tag not in tag and 'py3-none-any' not in tag and 'py2.py3-none-any' not in tag:
            continue  # wheel под другую версию/платформу
        try:
            with zipfile.ZipFile(str(whl)) as zf:
                zf.extractall(str(site_pkgs))
        except Exception as e:
            print(f'[setup]   [!] {whl.name}: {e}')
    # dist-info тоже должен быть на месте; повторная проверка импорта
    try:
        import flask  # noqa: F401
        import openpyxl  # noqa: F401
        print('[setup] OK: flask и openpyxl установлены автоматически.')
    except ImportError as e:
        print(f'[setup] [!] Автоустановить не удалось ({e}). Запустите tools\\install_offline.bat вручную.')

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / 'config.json'


def _load_config():
    if not CONFIG_PATH.exists():
        print(f'[!] Не найден {CONFIG_PATH}. Создайте файл config.json')
        sys.exit(1)
    try:
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    except Exception as e:
        print(f'[!] Ошибка чтения config.json: {e}')
        sys.exit(1)


def main():
    _ensure_site_packages()
    cfg = _load_config()
    from app import create_app
    try:
        app = create_app()
    except Exception as e:
        print(f'[!] Не удалось запустить приложение: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
    host = cfg.get('host', '0.0.0.0')
    port = int(cfg.get('port', 5431))
    debug = bool(cfg.get('debug', False))
    url = f'http://{"127.0.0.1" if host in ("0.0.0.0", "::") else host}:{port}/'

    print('=' * 60)
    print('  Трекер задач — standalone')
    print('=' * 60)
    print(f'  БД:   {cfg.get("db_path")}')
    print(f'  URL:  {url}')
    print('  Ctrl+C для остановки')
    print('=' * 60)

    if not debug and cfg.get('open_browser', True):
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)


if __name__ == '__main__':
    main()

