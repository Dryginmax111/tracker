"""plugins/db_cleanup.py — автоочистка audit_log и notifications."""
__version__ = '1.0'
__description__ = 'Автоочистка audit_log и notifications + VACUUM'

import sys
import threading
from datetime import datetime
from pathlib import Path

DEFAULTS = {
    'audit_days': 90,
    'notif_read_days': 30,
    'notif_done_days': 7,
    'interval_h': 24,
    'first_run_s': 300,
}

_STOP = threading.Event()


def _cfg(db):
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        try:
            v = db.get_setting('db_cleanup_' + k, None)
            if v is not None:
                out[k] = int(v)
        except Exception:
            pass
    try:
        out['enabled'] = str(db.get_setting('db_cleanup_enabled', '1')) != '0'
    except Exception:
        out['enabled'] = True
    return out


def _run_once(db, project_dir):
    cfg = _cfg(db)
    if not cfg.get('enabled', True):
        return
    base = Path(project_dir)
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))
    try:
        from cleanup_db import cleanup as _cleanup
    except Exception as e:
        print(f'[db_cleanup] import cleanup_db failed: {e}')
        return
    db_path = Path(getattr(db, 'path', '') or 'task_tracker.db')
    if not db_path.is_absolute():
        db_path = base / db_path
    try:
        _cleanup(str(db_path),
                 cfg['audit_days'],
                 cfg['notif_read_days'],
                 cfg['notif_done_days'],
                 dry=False, quiet=True)
        print(f'[db_cleanup] done {datetime.now():%Y-%m-%d %H:%M}')
    except Exception as e:
        print(f'[db_cleanup] cleanup failed: {e}')


def _worker(db, project_dir):
    cfg = _cfg(db)
    _STOP.wait(cfg['first_run_s'])
    while not _STOP.is_set():
        try:
            _run_once(db, project_dir)
        except Exception as e:
            print(f'[db_cleanup] loop error: {e}')
        cfg = _cfg(db)
        _STOP.wait(max(3600, cfg['interval_h'] * 3600))


def register(app, db, hooks):
    print(f'[db_cleanup] v{__version__} · {__description__}')
    project_dir = Path(app.root_path).resolve()

    def on_startup(**ctx):
        threading.Thread(target=_worker, args=(db, project_dir), daemon=True).start()

    def on_shutdown(**ctx):
        _STOP.set()

    hooks.on('on_startup', on_startup)
    hooks.on('on_shutdown', on_shutdown)
