#!/usr/bin/env python3
"""cleanup_db.py — очистка раздутых таблиц SQLite + VACUUM.

Использование:
    python cleanup_db.py               # ретеншены по умолчанию (90/30/7)
    python cleanup_db.py --dry         # только показать
    python cleanup_db.py --audit-days 180 --notif-days 60

Из кода:
    from cleanup_db import cleanup
    cleanup('/path/to/db', 90, 30, 7, dry=False)

Что чистит:
  audit_log:        строки старше audit_days (по умолчанию 90)
  notifications:
    - прочитанные (read_at != '') старше notif_read_days (30)
    - принятые/отклонённые (status IN confirmed/rejected) старше notif_done_days (7)
  VACUUM: автоматически, если освободилось >= 5 МБ (retry при 'database is locked')
  trk_debug.log: обрезается до 1 МБ (с конца — оставляем свежие записи)
  patch_backups: keep 20
  backups/db: keep 10
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

BASE = Path(__file__).parent.resolve()
CONFIG_PATH = BASE / 'config.json'


def _load_db_path(cli=None):
    if cli:
        return cli
    try:
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8')).get('db_path')
    except Exception:
        return None


def _db_size_bytes(p):
    try:
        return Path(p).stat().st_size
    except Exception:
        return 0


def _freelist_bytes(p):
    try:
        c = sqlite3.connect(str(p))
        try:
            pg = c.execute('PRAGMA page_size').fetchone()[0]
            fl = c.execute('PRAGMA freelist_count').fetchone()[0]
            return pg * fl
        finally:
            c.close()
    except Exception:
        return 0


def _count(c, sql, params=()):
    try:
        return c.execute(sql, params).fetchone()[0]
    except Exception:
        return 0


def _trim_log(dbg, keep_bytes=1024 * 1024, quiet=False):
    """PATCH 1.0.1-fix: режем С КОНЦА, чтобы оставить свежие записи."""
    if not dbg.exists() or dbg.stat().st_size <= keep_bytes:
        return
    try:
        with dbg.open('rb+') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - keep_bytes))
            tail = f.read()
            f.seek(0)
            f.write(tail)
            f.truncate()
        if not quiet:
            print(f'  trk_debug.log: {size / 1024 / 1024:.1f} МБ -> 1 МБ (свежие записи)')
    except Exception as e:
        if not quiet:
            print(f'  ! trk_debug.log: {e}')


def cleanup(db_path, audit_days=90, notif_read_days=30, notif_done_days=7, dry=False, quiet=False):
    src = Path(db_path)
    if not src.is_absolute():
        src = BASE / src
    if not src.exists():
        if not quiet:
            print(f'! БД не найдена: {src}')
        return 1
    before = _db_size_bytes(src)
    c = sqlite3.connect(str(src), timeout=30.0)
    total_deleted = 0
    try:
        # PATCH 1.0.1: гарантируем индексы для быстрого DELETE
        try:
            c.execute('CREATE INDEX IF NOT EXISTS idx_notif_read ON notifications (read_at)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_notif_ts ON notifications (ts)')
        except Exception:
            pass

        cutoff_audit = f'-{int(audit_days)} days'
        old = _count(c, "SELECT COUNT(*) FROM audit_log WHERE ts < datetime('now','localtime',?)", (cutoff_audit,))
        if old and not dry:
            c.execute("DELETE FROM audit_log WHERE ts < datetime('now','localtime',?)", (cutoff_audit,))
        if not quiet:
            print(f'  audit_log: < {audit_days} дн. -> {old}')
        total_deleted += old

        cutoff_read = f'-{int(notif_read_days)} days'
        old = _count(c, "SELECT COUNT(*) FROM notifications WHERE read_at != '' AND read_at < datetime('now','localtime',?)", (cutoff_read,))
        if old and not dry:
            c.execute("DELETE FROM notifications WHERE read_at != '' AND read_at < datetime('now','localtime',?)", (cutoff_read,))
        if not quiet:
            print(f'  notifications (read): < {notif_read_days} дн. -> {old}')
        total_deleted += old

        cutoff_done = f'-{int(notif_done_days)} days'
        old = _count(c, "SELECT COUNT(*) FROM notifications WHERE status IN ('rejected','confirmed') AND ts < datetime('now','localtime',?)", (cutoff_done,))
        if old and not dry:
            c.execute("DELETE FROM notifications WHERE status IN ('rejected','confirmed') AND ts < datetime('now','localtime',?)", (cutoff_done,))
        if not quiet:
            print(f'  notifications (rej/conf): < {notif_done_days} дн. -> {old}')
        total_deleted += old

        if not dry:
            c.commit()
    finally:
        c.close()

    if not dry and total_deleted > 0:
        fl = _freelist_bytes(src)
        freed_mb = fl / 1024 / 1024
        if freed_mb >= 5:
            if not quiet:
                print(f'  VACUUM (освободится ~{freed_mb:.1f} МБ)...')
            # PATCH 1.0.1: retry при 'database is locked'
            for attempt in range(3):
                vc = None
                try:
                    vc = sqlite3.connect(str(src), timeout=120.0)
                    vc.execute('VACUUM')
                    vc.close()
                    if not quiet:
                        print('  VACUUM завершён')
                    break
                except Exception as e:
                    try:
                        if vc is not None:
                            vc.close()
                    except Exception:
                        pass
                    if 'locked' in str(e).lower() and attempt < 2:
                        time.sleep(2)
                        continue
                    if not quiet:
                        print(f'  ! VACUUM не удался: {e}')
                    break

    _trim_log(BASE / 'trk_debug.log', quiet=quiet)

    def _trim_dir(d, glob_pat, keep, label):
        if not d.exists():
            return
        files = sorted(d.glob(glob_pat), key=lambda p: p.stat().st_mtime, reverse=True)
        if len(files) <= keep:
            return
        for f in files[keep:]:
            if dry:
                if not quiet:
                    print(f'  {label}: удалить {f.name}')
                continue
            try:
                f.unlink()
            except Exception:
                pass

    _trim_dir(BASE / 'patch_backups', '**/*.bak-*', 20, 'patch_backups')
    _trim_dir(src.parent / 'backups' / 'db', 'db_*.db', 10, 'backups/db')

    after = _db_size_bytes(src)
    if not quiet:
        print()
        print(f'До:    {before / 1024 / 1024:.2f} МБ')
        print(f'После: {after / 1024 / 1024:.2f} МБ')
        if after < before:
            print(f'Освобождено: {(before - after) / 1024 / 1024:.2f} МБ')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=None)
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--audit-days', type=int, default=90)
    ap.add_argument('--notif-days', type=int, default=30)
    ap.add_argument('--notif-done-days', type=int, default=7)
    args = ap.parse_args()
    db = _load_db_path(args.db)
    if not db:
        print('! Не найден config.json или db_path')
        return 1
    return cleanup(db, args.audit_days, args.notif_days, args.notif_done_days, args.dry)


if __name__ == '__main__':
    sys.exit(main())
