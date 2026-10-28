"""plugins/updater.py — проверка, применение и откат обновлений (Manifest-less v3)."""
__version__ = '2.3'
__description__ = 'Обновления: сканирование папки, dry-run, применение, откат без манифеста'

import os
import re
import hashlib
import json
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from flask import jsonify, Response, redirect, request

PLUGIN_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = PLUGIN_DIR.parent
JOURNAL_PATH = PROJECT_DIR / '.patches_applied.json'
CONFIG_PATH = PROJECT_DIR / 'config.json'
VERSION_PATH = PROJECT_DIR / 'client_version.json'
PATCHER_PATH = PROJECT_DIR / 'patcher.py'
STAGE_ROOT = PROJECT_DIR / 'patch_runs' / 'plugin_stage'
LOCK_PATH = PROJECT_DIR / '.updater.lock'

BASE_VERSION = '1.0.0'
LOCK_STALE_SEC = 15 * 60


# ============================================================
# Атомарная запись и lock
# ============================================================
def _atomic_write_text(path, text):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)


class _UpdaterLock:
    def __init__(self, path, stale_sec=LOCK_STALE_SEC):
        self.path = path
        self.stale_sec = stale_sec
        self.fd = None

    def acquire(self):
        if self.path.exists():
            try:
                age = time.time() - self.path.stat().st_mtime
                if age > self.stale_sec:
                    self.path.unlink()
            except Exception:
                pass
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.fd, str(os.getpid()).encode('utf-8'))
            return True
        except FileExistsError:
            return False
        except Exception as e:
            print(f'[updater] lock acquire failed: {e}')
            return False

    def release(self):
        try:
            if self.fd is not None:
                os.close(self.fd)
        except Exception:
            pass
        try:
            self.path.unlink()
        except Exception:
            pass
        self.fd = None


# ============================================================
# Версия
# ============================================================
def _read_version():
    if not VERSION_PATH.exists():
        _write_version(BASE_VERSION, 'base')
        return {'version': BASE_VERSION, 'updated_at': '', 'last_patch_id': 'base'}
    try:
        d = json.loads(VERSION_PATH.read_text(encoding='utf-8'))
        if not isinstance(d, dict):
            return {'version': BASE_VERSION, 'updated_at': '', 'last_patch_id': ''}
        return d
    except Exception:
        return {'version': BASE_VERSION, 'updated_at': '', 'last_patch_id': ''}


def _write_version(version, last_patch_id):
    data = {
        'version': str(version),
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'last_patch_id': str(last_patch_id or ''),
    }
    _atomic_write_text(VERSION_PATH, json.dumps(data, ensure_ascii=False, indent=2))
    return data


def _ver_tuple(v):
    # PATCH v1.0.5: раньше '1.1.1b' падал на int('1b') → (0,0,0), и патч
    # с суффиксом оказывался «первым в очереди». Теперь берём только
    # числовую часть каждого сегмента: '1.1.1b' → (1,1,1), '1.0.0-rc' → (1,0,0).
    try:
        import re as _re_ver
        parts = str(v or '').strip().split('.')
        out = []
        for p in parts[:3]:
            m = _re_ver.match(r'(\d+)', p)
            out.append(int(m.group(1)) if m else 0)
        while len(out) < 3:
            out.append(0)
        return tuple(out)
    except Exception:
        return (0, 0, 0)


def _ver_cmp(a, b):
    ta, tb = _ver_tuple(a), _ver_tuple(b)
    return -1 if ta < tb else (1 if ta > tb else 0)


# ============================================================
# Конфиг / журнал / утилиты
# ============================================================
def _read_config():
    try:
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _read_journal_strict():
    """PATCH v1.0.11: громкая ошибка при битом журнале.

    Возвращает {} только если файла нет. Если файл есть, но не парсится —
    бросает RuntimeError. Apply/rollback/check обязаны использовать эту
    функцию: иначе патчи начнут применяться «с нуля», файл будет перезаписан,
    и история (с путями к бэкапам) потеряется.
    """
    if not JOURNAL_PATH.exists():
        return {}
    try:
        _raw = JOURNAL_PATH.read_text(encoding='utf-8-sig')
        _data = json.loads(_raw)
        if not isinstance(_data, dict):
            raise ValueError('корень не объект')
        return _data
    except Exception as e:
        raise RuntimeError(
            f'Журнал {JOURNAL_PATH.name} повреждён: {e}. '
            f'Применение и откат заблокированы. '
            f'Восстановите из .patches_applied.archive-*.json или '
            f'удалите файл вручную (потеряете историю применения).'
        )


def _read_journal():
    """Безопасное чтение для read-only эндпоинтов (возвращает {} при ошибке).

    Apply/rollback/check обязаны использовать _read_journal_strict().
    """
    try:
        return _read_journal_strict()
    except Exception:
        return {}


def _sha256_file(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _auth_ok(db, need_apply=False):
    try:
        from auth import current_user, user_has
        u = current_user(db)
        if not u:
            return None
        if not user_has(db, u, 'tab.updater'):
            return None
        if need_apply and not user_has(db, u, 'action.updater.apply'):
            return None
        return u
    except Exception as e:
        print(f'[updater] auth_ok failed: {e}')
    return None


def _share_dir():
    cfg = _read_config()
    nu = cfg.get('net_update') or {}
    if not nu.get('enabled', True):
        return None, 'обновление из сети отключено'
    sp = (nu.get('share_path') or '').strip()
    if not sp:
        return None, 'net_update.share_path не задан'
    p = Path(sp)
    if not p.is_absolute():
        p = PROJECT_DIR / p       # <-- фикс: относительный путь — от корня проекта
    if not p.exists() or not p.is_dir():
        return None, f'папка недоступна: {p}'
    return p, None



# ============================================================
# Сканирование
# ============================================================
def _scan_patches(share_dir, skipped_out=None):
    """PATCH 1.0.11: показывает причину пропуска; читает BOM; сортирует по имени."""
    patches = []
    if not share_dir:
        return patches
    for f in sorted(share_dir.glob('*.json')):
        if f.name.lower() == 'manifest.json':
            continue
        try:
            raw = f.read_text(encoding='utf-8-sig')
        except Exception as e:
            if skipped_out is not None:
                skipped_out.append({'file': f.name, 'reason': 'не удалось прочитать: ' + str(e)})
            continue
        try:
            data = json.loads(raw)
        except Exception as e:
            if skipped_out is not None:
                skipped_out.append({'file': f.name, 'reason': 'битый JSON: ' + str(e)})
            continue
        if not isinstance(data, dict):
            if skipped_out is not None:
                skipped_out.append({'file': f.name, 'reason': 'корень не объект'})
            continue
        if 'id' not in data:
            if skipped_out is not None:
                skipped_out.append({'file': f.name, 'reason': 'нет поля id'})
            continue
        if 'operations' not in data:
            if skipped_out is not None:
                skipped_out.append({'file': f.name, 'reason': 'нет поля operations'})
            continue
        data['file'] = f.name
        patches.append(data)
    return patches


def _parse_patches_order(patches, applied_ids=None):
    if not isinstance(patches, list):
        return [], 'ожидался список патчей'
    patch_map = {p.get('id'): p for p in patches if p.get('id')}
    seen = set(applied_ids or [])   # <-- ключевое: знаем про применённые
    out = []
    remaining = list(patch_map.values())
    guard = 0
    max_iter = max(len(patch_map) * 3, 40)
    while remaining and guard < max_iter:
        guard += 1
        ready = [p for p in remaining
                 if all(r in seen for r in (p.get('requires') or []))]
        if not ready:
            break
        ready.sort(key=lambda x: (_ver_tuple(x.get('target_version', '0.0.0')), x.get('id', '')))
        pick = ready[0]
        out.append(pick)
        seen.add(pick.get('id'))
        remaining.remove(pick)
    if remaining:
        for _p in remaining:
            _reqs = _p.get('requires') or []
            _missing = [r for r in _reqs if r not in seen]
            if _missing:
                _p['_skip_reason'] = 'требует патчи: ' + ', '.join(_missing)
            out.append(_p)
    return out, None

def _current_version():
    return _read_version().get('version', BASE_VERSION)


def _extract_version_from_id(pid):
    m = re.search(r'(\d+)\.(\d+)\.(\d+)', str(pid or ''))
    if m:
        return f'{m.group(1)}.{m.group(2)}.{m.group(3)}'
    return ''


def _journal_table(journal):
    out = []
    for pid, info in journal.items():
        info = info or {}
        ver = (info.get('target_version') or '').strip()
        if not ver:
            ver = _extract_version_from_id(pid)
        out.append({
            'id': pid,
            'applied_at': info.get('applied_at') or '',
            'description': info.get('description') or '',
            'ops': info.get('operations_count') or 0,
            'version': ver,
        })

    def sort_key(x):
        ver = x.get('version') or '0.0.0'
        try:
            vp = tuple(int(p) for p in ver.split('.'))
            while len(vp) < 3:
                vp += (0,)
        except Exception:
            vp = (0, 0, 0)
        return (x.get('applied_at') or '', vp, x.get('id') or '')

    out.sort(key=sort_key, reverse=True)
    return out


def _safe_journal_table(journal):
    try:
        return _journal_table(journal)[:200]
    except Exception as e:
        print(f'[updater] _journal_table failed: {e}')
        try:
            good = {k: v for k, v in (journal or {}).items() if isinstance(v, dict)}
            return _journal_table(good)[:200]
        except Exception as e2:
            print(f'[updater] _journal_table retry failed: {e2}')
            return []


def _effective_version(manifest_mock, journal):
    # 1) Патчи из сетевой папки
    ordered = list(manifest_mock.get('patches', []))
    share_ids = {p.get('id') for p in ordered if p.get('id')}

    # 2) Патчи из журнала, которых нет в папке — они уже применены,
    #    версия должна их учитывать.
    for pid, info in (journal or {}).items():
        if not pid or pid in share_ids:
            continue
        ver = (info.get('target_version') or '').strip()
        if not ver:
            ver = _extract_version_from_id(pid)
        if not ver:
            continue
        ordered.append({
            'id': pid,
            'target_version': ver,
            'requires': [],
            'file': '',
            '_from_journal': True,
        })

    # 3) Сортируем по target_version
    ordered.sort(key=lambda x: (
        _ver_tuple(x.get('target_version', '0.0.0')),
        x.get('id', '')
    ))

    if not ordered:
        return {
            'chain_version': BASE_VERSION,
            'last_applied_id': '',
            'last_applied_version': BASE_VERSION,
            'missing_ids': [],
            'broken_at': '',
        }

    applied = set(journal.keys())
    chain_v = BASE_VERSION
    broken_at = ''
    missing_ids = []
    last_applied_id = ''
    last_applied_version = BASE_VERSION

    for p in ordered:
        pid = p.get('id')
        tv = p.get('target_version') or ''
        if pid in applied:
            last_applied_id = pid
            if tv:
                last_applied_version = tv
            if broken_at:
                continue
            if tv:
                chain_v = tv
            continue
        if broken_at:
            continue
        if p.get('independent'):
            continue
        broken_at = pid
        missing_ids.append(pid)

    return {
        'chain_version': chain_v,
        'last_applied_id': last_applied_id,
        'last_applied_version': last_applied_version,
        'missing_ids': missing_ids,
        'broken_at': broken_at,
    }

def _recompute_version_from_manifest(manifest_mock):
    journal = _read_journal()
    info = _effective_version(manifest_mock, journal)
    _write_version(info['chain_version'], info['last_applied_id'])
    return info['chain_version']


# ============================================================
# Статус
# ============================================================
def _status(share_dir, journal):
    local_v = _current_version()
    st = {
        'version': local_v,
        'applied_count': len(journal),
        'journal': _safe_journal_table(journal),
        'share_ok': False,
        'share_path': str(share_dir) if share_dir else '',
        'share_error': '',
        'manifest_version': 'N/A (Scan Mode)',
        'manifest_created': '',
        'remote_version': '',
        'pending': [],
        'status': 'unknown',
        'status_text': '',
        'chain_version': local_v,
        'missing_ids': [],
        'broken_at': '',
        'skipped_files': [],
    }
    if not share_dir:
        st['share_error'] = 'папка не задана'
        return st

    st['share_ok'] = True
    _skipped = []
    patches = _scan_patches(share_dir, skipped_out=_skipped)
    st['skipped_files'] = _skipped
    ordered, perr = _parse_patches_order(patches, journal.keys())
    if perr:
        st['share_error'] = perr
        return st

    eff_info = _effective_version({'patches': ordered}, journal)
    st['chain_version'] = eff_info['chain_version']
    st['missing_ids'] = eff_info['missing_ids']
    st['broken_at'] = eff_info['broken_at']
    st['last_applied_id'] = eff_info['last_applied_id']
    st['last_applied_version'] = eff_info['last_applied_version']

    if eff_info['chain_version'] != local_v:
        st['version'] = eff_info['chain_version']

    applied_ids = set(journal.keys())
    pending = []
    projected = eff_info['chain_version']

    for p in ordered:
        pid = p.get('id')
        if pid in applied_ids:
            tv = p.get('target_version')
            if tv:
                projected = tv
            continue
        req_v = p.get('requires_version')
        if req_v and _ver_cmp(projected, req_v) < 0:
            p['_skip_reason'] = f'требуется ≥ {req_v}, будет {projected}'
        pending.append(p)
        tv = p.get('target_version')
        if tv:
            projected = tv

    st['pending'] = [{
        'id': p.get('id'),
        'file': p.get('file'),
        'requires': p.get('requires') or [],
        'requires_version': p.get('requires_version') or '',
        'target_version': p.get('target_version') or '',
        'skip_reason': p.get('_skip_reason') or '',
        'description': p.get('description') or '',
    } for p in pending]

    if pending:
        _vers = [p.get('target_version') for p in pending if p.get('target_version')]
        remote = max(_vers, key=_ver_tuple) if _vers else st['version']
        st['remote_version'] = remote
        if _ver_cmp(remote, st['version']) > 0:
            st['status'] = 'available'
            st['status_text'] = f'Доступно обновление {st["version"]} → {remote}'
        else:
            st['status'] = 'available'
            st['status_text'] = 'Есть патчи к применению'
    else:
        st['remote_version'] = st['version']
        st['status'] = 'actual'
        st['status_text'] = 'Установлена актуальная версия'
    return st


# ============================================================
# Проверка патчей
# ============================================================
def _verify_patches(share_dir, patches, local_version):
    out = []
    projected = local_version
    chain_broken_at = None
    seen_ok_ids = set()
    try:
        journal_ids = set(_read_journal().keys())
    except Exception:
        journal_ids = set()

    for idx, p in enumerate(patches):
        pid = p.get('id')
        fname = p.get('file') or ''
        is_indep = bool(p.get('independent'))
        entry = {'id': pid, 'ok': True, 'error': '', 'warning': '', 'independent': is_indep}

        _skip_rsn = p.get('_skip_reason')
        if _skip_rsn:
            entry['warning'] = _skip_rsn
            out.append(entry)
            continue

        if chain_broken_at is not None and not is_indep:
            prev_pid = patches[chain_broken_at].get('id') if 0 <= chain_broken_at < len(patches) else '?'
            entry['ok'] = False
            entry['error'] = f'зависит от патча «{prev_pid}», который не прошёл проверку'
            out.append(entry)
            continue

        reqs = p.get('requires') or []
        if reqs:
            missing_req = [r for r in reqs if r not in seen_ok_ids and r not in journal_ids]
            if missing_req:
                entry['ok'] = False
                entry['error'] = 'требует патчи: ' + ', '.join(missing_req)
                if not is_indep:
                    chain_broken_at = idx
                out.append(entry)
                continue

        try:
            if not fname:
                entry['ok'] = False
                entry['error'] = 'нет поля file'
                if not is_indep:
                    chain_broken_at = idx
                out.append(entry)
                continue
            src = share_dir / fname
            if not src.exists():
                entry['ok'] = False
                entry['error'] = f'файл не найден: {fname}'
                if not is_indep:
                    chain_broken_at = idx
                out.append(entry)
                continue
            req_v = p.get('requires_version')
            if req_v and _ver_cmp(projected, req_v) < 0:
                entry['ok'] = False
                entry['error'] = f'требуется версия ≥ {req_v}, будет {projected}'
                if not is_indep:
                    chain_broken_at = idx
                out.append(entry)
                continue
            try:
                json.loads(src.read_text(encoding='utf-8'))
            except Exception as e:
                entry['ok'] = False
                entry['error'] = f'невалидный JSON патча: {e}'
                if not is_indep:
                    chain_broken_at = idx
                out.append(entry)
                continue
        except Exception as e:
            entry['ok'] = False
            entry['error'] = f'непредвиденная ошибка: {e}'
            if not is_indep:
                chain_broken_at = idx
            out.append(entry)
            continue

        tv = p.get('target_version')
        if tv:
            projected = tv
        seen_ok_ids.add(pid)
        out.append(entry)
    return out


def _stage(share_dir, patches, ts):
    stage_dir = STAGE_ROOT / ts
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    for p in patches:
        src = share_dir / p['file']
        dst = stage_dir / p['file']
        shutil.copy2(src, dst)
    return stage_dir


def _run_subprocess(cmd, timeout):
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    try:
        proc = subprocess.run(
            cmd, cwd=str(PROJECT_DIR),
            capture_output=True, encoding='utf-8', errors='replace',
            env=env, timeout=timeout,
        )
        return proc.returncode, (proc.stdout or '') + (proc.stderr or '')
    except subprocess.TimeoutExpired:
        return 124, f'таймаут {timeout}s'
    except Exception as e:
        return 1, f'ошибка запуска: {e}'


def _run_patcher(stage_dir, dry, timeout=180):
    cmd = [sys.executable, str(PATCHER_PATH), str(stage_dir)]
    if dry:
        cmd.append('--dry')
    return _run_subprocess(cmd, timeout)


def _run_patcher_rollback(pid, timeout=120):
    cmd = [sys.executable, str(PATCHER_PATH), '--rollback', pid]
    return _run_subprocess(cmd, timeout)


def _collect_pending(share, journal, local_v):
    patches = _scan_patches(share)
    ordered, perr = _parse_patches_order(patches, journal.keys())
    if perr:
        return None, None, perr
    applied_ids = set(journal.keys())
    pending = [p for p in ordered
               if (p.get('id') or Path(p.get('file', '')).stem) not in applied_ids]
    return ordered, pending, None


# ============================================================
# JS — удаление устаревшей кнопки (миграция)
# ============================================================
_JS = r'''
(function(){
'use strict';
function cleanup(){
    var old = document.getElementById('updaterBtn');
    if (old && old.parentNode) old.parentNode.removeChild(old);
}
cleanup();
setTimeout(cleanup, 800);
setTimeout(cleanup, 2000);
})();
'''


# ============================================================
# HTML
# ============================================================
def _page_html():
    return r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Обновления</title>
<script>window.REESTR_CSRF = "__CSRF_TOKEN__"; window.UPDATER_CAN_APPLY = ("__CAN_APPLY__" === "true");</script>
<script src="/static/plugin_theme.js"></script>
<style>
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; margin: 0; padding: 16px; font-size: 14px; background: var(--pg-bg, #0f0f0f); background-attachment: fixed; color: var(--pg-text, #e8e8e8); min-height: 100vh; }
.w { max-width: 1200px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.head { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 14px 18px; background: var(--pg-card-bg, #1a1a1a); border: 1px solid var(--pg-card-border, rgba(245,215,110,0.22)); border-radius: 14px; }
.head h1 { margin: 0; font-size: 1.2rem; font-weight: 800; color: var(--pg-accent, #f5d76e); }
.back { color: var(--pg-desc, #c8c8c8); text-decoration: none; padding: 6px 14px; border: 1px solid var(--pg-card-border); border-radius: 20px; font-size: 0.85rem; }
.back:hover { background: var(--pg-accent-bg); color: var(--pg-accent); border-color: var(--pg-accent); }
.version-banner { padding: 20px 24px; background: var(--pg-card-bg); border: 1px solid var(--pg-card-border); border-radius: 16px; display: grid; grid-template-columns: auto 1fr auto auto; gap: 20px; align-items: center; }
.version-banner.ok { border-left: 5px solid var(--pg-ok, #58d68d); }
.version-banner.warn { border-left: 5px solid var(--pg-warn, #f7dc6f); }
.version-banner.err { border-left: 5px solid var(--pg-err, #ec7063); }
.version-banner.info { border-left: 5px solid var(--pg-info, #6dc2f0); }
.vb-icon { font-size: 2.4rem; line-height: 1; }
.vb-title { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.9px; color: var(--pg-meta); font-weight: 800; }
.vb-sub { font-size: 1rem; color: var(--pg-text); margin-top: 4px; font-weight: 600; }
.vb-versions { display: flex; align-items: center; gap: 14px; font-family: monospace; font-size: 1.35rem; font-weight: 800; padding: 8px 18px; border-radius: 12px; background: var(--pg-inner-bg); }
.vb-versions .vlocal { color: var(--pg-text); }
.vb-versions .vremote { color: var(--pg-accent); }
.vb-versions .arrow { color: var(--pg-meta); font-size: 1.4rem; }
.vb-refresh { width: 38px; height: 38px; border-radius: 50%; border: 1px solid var(--pg-card-border); background: transparent; color: var(--pg-desc); cursor: pointer; font-size: 1.05rem; display: inline-flex; align-items: center; justify-content: center; font-family: inherit; transition: all .15s; }
.vb-refresh:hover { background: var(--pg-accent-bg); border-color: var(--pg-accent); color: var(--pg-accent); }
.vb-refresh.spin { animation: spin .6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.status-bar { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
.stat-card { padding: 14px 16px; background: var(--pg-card-bg); border: 1px solid var(--pg-card-border); border-radius: 12px; }
.stat-card .v { font-size: 1.3rem; font-weight: 800; line-height: 1.1; color: var(--pg-accent); word-break: break-word; font-family: monospace; }
.stat-card .l { font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.8px; color: var(--pg-meta); font-weight: 700; margin-top: 4px; }
.stat-card.ok .v { color: var(--pg-ok); }
.stat-card.warn .v { color: var(--pg-warn); }
.stat-card.err .v { color: var(--pg-err); }
.stat-card.info .v { color: var(--pg-info); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; font-size: 1rem; }
.card { padding: 18px 20px; background: var(--pg-card-bg); border: 1px solid var(--pg-card-border); border-radius: 14px; }
.card-title { display: flex; align-items: center; gap: 8px; font-size: 0.78rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.8px; color: var(--pg-accent); margin-bottom: 14px; padding-bottom: 8px; border-bottom: 1px dashed var(--pg-card-border-soft); }
.card-title .cnt { margin-left: auto; font-size: 0.7rem; padding: 1px 8px; border-radius: 8px; background: var(--pg-accent-bg); color: var(--pg-accent); font-weight: 700; }
.step-row { display: grid; grid-template-columns: 40px 1fr auto; gap: 16px; align-items: center; padding: 16px 0; }
.step-row + .step-row { border-top: 1px dashed var(--pg-card-border-soft); }
.step-row:first-child { padding-top: 0; }
.step-row:last-child { padding-bottom: 0; }
.step-num { width: 36px; height: 36px; border-radius: 50%; background: var(--pg-inner-bg); color: var(--pg-accent); font-size: 1.05rem; font-weight: 800; display: flex; align-items: center; justify-content: center; border: 2px solid var(--pg-accent); flex-shrink: 0; }
.step-body { min-width: 0; }
.step-title { font-size: 0.95rem; font-weight: 800; color: var(--pg-text); }
.step-desc { font-size: 0.8rem; color: var(--pg-meta); margin-top: 3px; line-height: 1.4; }
.check-result { margin-left: 56px; padding: 12px 0 16px 0; border-top: 1px dashed var(--pg-card-border-soft); }
.check-result-title { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.8px; color: var(--pg-meta); font-weight: 800; margin-bottom: 8px; }
.btn { padding: 10px 20px; border-radius: 10px; cursor: pointer; border: none; font-family: inherit; font-size: 0.88rem; font-weight: 700; transition: all 0.15s; display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; }
.btn:hover:not(:disabled) { transform: translateY(-1px); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-primary { background: linear-gradient(135deg, var(--pg-accent), var(--pg-accent-2)); color: #0a0a0a; }
.btn-secondary { background: transparent; border: 1px solid var(--pg-card-border); color: var(--pg-desc); }
.btn-secondary:hover:not(:disabled) { border-color: var(--pg-accent); color: var(--pg-accent); }
.btn-danger { background: rgba(231,76,60,0.15); border: 1px solid rgba(231,76,60,0.4); color: var(--pg-err); padding: 4px 10px; font-size: 0.75rem; }
.btn-danger:hover:not(:disabled) { background: rgba(231,76,60,0.25); border-color: var(--pg-err); }
.patch-row { display: grid; grid-template-columns: 24px 1fr auto; gap: 10px; align-items: center; padding: 8px 10px; background: var(--pg-inner-bg); border-radius: 8px; margin-bottom: 4px; border-left: 3px solid var(--pg-meta); font-size: 0.83rem; }
.patch-row.ok { border-left-color: var(--pg-ok); }
.patch-row.err { border-left-color: var(--pg-err); }
.patch-row.warn { border-left-color: var(--pg-warn); }
.patch-row .ico { font-size: 1rem; text-align: center; }
.patch-row .id { font-family: monospace; font-weight: 700; color: var(--pg-text); }
.patch-row .ver { font-size: 0.72rem; color: var(--pg-meta); margin-top: 2px; }
.patch-row .desc { font-size: 0.78rem; color: var(--pg-desc); margin-top: 3px; line-height: 1.4; word-break: break-word; }
.patch-row .err-msg { font-size: 0.72rem; color: var(--pg-err); margin-top: 2px; word-break: break-word; }
.patch-row .warn-msg { font-size: 0.72rem; color: var(--pg-warn); margin-top: 2px; word-break: break-word; }
.log-box { margin-top: 10px; padding: 10px 12px; background: #0a0a0a; border-radius: 8px; font-family: monospace; font-size: 0.75rem; color: #c8c8c8; max-height: 260px; overflow-y: auto; white-space: pre-wrap; word-break: break-word; border: 1px solid var(--pg-card-border-soft); }
body.trk-theme-light .log-box { background: #f7f9fa; color: #212121; }
.log-label { font-size: 0.7rem; text-transform: uppercase; color: var(--pg-meta); font-weight: 700; margin-top: 10px; }
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
table th { text-align: left; padding: 6px 8px; font-size: 0.66rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.6px; color: var(--pg-meta); border-bottom: 1px solid var(--pg-card-border-soft); white-space: nowrap; }
table th.num, table td.num { text-align: right; }
table td { padding: 6px 8px; border-bottom: 1px solid var(--pg-card-border-soft); color: var(--pg-text); }
table tr:hover td { background: var(--pg-inner-bg); }
table td.muted { color: var(--pg-meta); }
table td.actions { text-align: right; white-space: nowrap; }
.journal-table .day-sep td { background: transparent; padding: 12px 0 6px; border-bottom: 1px solid var(--pg-card-border-soft); color: var(--pg-accent); font-weight: 800; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.8px; font-family: monospace; }
.journal-table .day-sep:hover td { background: transparent; }
.ver-pill { display: inline-block; padding: 2px 8px; border-radius: 8px; font-family: monospace; font-weight: 800; font-size: 0.75rem; background: var(--pg-accent-bg); color: var(--pg-accent); }
.ver-none { color: var(--pg-meta); font-family: monospace; }
.j-id { font-family: monospace; font-size: 0.78rem; font-weight: 700; color: var(--pg-text); word-break: break-all; }
.j-desc { font-size: 0.72rem; color: var(--pg-meta); margin-top: 3px; line-height: 1.35; }
.empty, .loading { text-align: center; padding: 24px; color: var(--pg-meta); font-style: italic; font-size: 0.82rem; }
.rollback-hint { font-size: 0.87rem; color: var(--pg-desc); line-height: 1.55; }
.rollback-hint b { color: var(--pg-accent); }
.modal-overlay { position: fixed; inset: 0; z-index: 4000; background: rgba(0,0,0,0.55); backdrop-filter: blur(6px); display: none; align-items: center; justify-content: center; padding: 20px; }
.modal-overlay.active { display: flex; }
.modal-box { max-width: 560px; width: 100%; background: var(--pg-card-bg); border: 1px solid var(--pg-card-border); border-radius: 18px; padding: 22px 26px; box-shadow: 0 20px 60px rgba(0,0,0,0.55); }
.modal-box h2 { margin: 0 0 14px; font-size: 1.15rem; font-weight: 800; display: flex; align-items: center; gap: 10px; }
.modal-box h2.ok { color: var(--pg-ok); }
.modal-box h2.err { color: var(--pg-err); }
.modal-box h2.warn { color: var(--pg-warn); }
.modal-icon { font-size: 1.7rem; }
.modal-body { font-size: 0.9rem; line-height: 1.55; color: var(--pg-text); }
.modal-body .hl { color: var(--pg-accent); font-weight: 700; }
.up-spinner {
    display: inline-block;
    width: 36px; height: 36px;
    border: 3px solid rgba(245,215,110,0.25);
    border-top-color: #f5d76e;
    border-radius: 50%;
    animation: upSpin 0.75s linear infinite;
}
@keyframes upSpin { to { transform: rotate(360deg); } }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 18px; }
@media (max-width: 700px) {
    .head { padding: 12px 14px; }
    .head h1 { font-size: 1rem; }
    .version-banner { grid-template-columns: auto 1fr; text-align: left; }
    .version-banner .vb-versions { grid-column: 1 / -1; justify-content: center; }
    .version-banner .vb-refresh { grid-column: 2; grid-row: 1; justify-self: end; }
    .step-row { grid-template-columns: 36px 1fr; gap: 12px; }
    .step-row .btn { grid-column: 1 / -1; justify-self: stretch; justify-content: center; }
    .check-result { margin-left: 0; }
}

/* PATCH v1.1.1b updater-modal-scroll-fix: фикс. высота + скролл списка патчей */
#updaterCheckModal.modal-overlay {
    display: none;
    position: fixed;
    inset: 0;
    z-index: 4000;
    background: rgba(0,0,0,0.55);
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    align-items: center;
    justify-content: center;
    padding: 20px;
    box-sizing: border-box;
}
#updaterCheckModal.modal-overlay.active {
    display: flex;
}
#updaterCheckModal .updater-check-box {
    display: flex !important;
    flex-direction: column !important;
    width: 100%;
    max-width: 640px;
    height: 85vh;
    max-height: 780px;
    min-height: 360px;
    margin: 0;
    padding: 0 !important;
    overflow: hidden;
    background: var(--pg-card-bg, #1a1a1a);
    border: 1px solid var(--pg-card-border, rgba(245,215,110,0.22));
    border-radius: 18px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.55);
}
#updaterCheckModal .updater-check-title {
    flex: 0 0 auto !important;
    margin: 0 !important;
    padding: 18px 22px 14px !important;
    border-bottom: 1px solid rgba(128,128,128,0.2);
    font-size: 1.1rem;
    display: flex;
    align-items: center;
    gap: 10px;
}
#updaterCheckModal #ucBody {
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow-y: auto !important;
    padding: 16px 22px !important;
    scrollbar-width: thin;
    scrollbar-color: rgba(245,215,110,0.5) rgba(128,128,128,0.1);
}
#updaterCheckModal #ucBody::-webkit-scrollbar { width: 8px; }
#updaterCheckModal #ucBody::-webkit-scrollbar-track {
    background: rgba(128,128,128,0.08);
    border-radius: 4px;
}
#updaterCheckModal #ucBody::-webkit-scrollbar-thumb {
    background: rgba(128,128,128,0.3);
    border-radius: 4px;
}
#updaterCheckModal #ucBody::-webkit-scrollbar-thumb:hover {
    background: var(--pg-accent, #f5d76e);
}
#updaterCheckModal .updater-check-footer {
    flex: 0 0 auto !important;
    padding: 12px 22px 16px !important;
    border-top: 1px solid rgba(128,128,128,0.2);
    background: var(--pg-card-bg, #1a1a1a);
}
#updaterCheckModal .updater-check-auto {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    margin-bottom: 10px;
    background: var(--pg-inner-bg, rgba(128,128,128,0.1));
    border-radius: 8px;
    font-size: 0.85rem;
    color: var(--pg-text, #e8e8e8);
    cursor: pointer;
    user-select: none;
}
#updaterCheckModal .updater-check-auto input[type="checkbox"] {
    width: 16px;
    height: 16px;
    margin: 0;
    flex: 0 0 auto;
    accent-color: var(--pg-accent, #f5d76e);
}
#updaterCheckModal .updater-check-footer .modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin: 0;
}
body.trk-theme-light #updaterCheckModal .updater-check-box,
body.trk-theme-light #updaterCheckModal .updater-check-footer {
    background: #ffffff;
}
</style>
</head>
<body>
<div class="w">
    <div class="head">
        <a class="back" href="/">← К трекеру</a>
        <h1>⬆ Обновления</h1>
    </div>
    <div id="versionBanner"></div>
    <div id="chainWarn" style="display:none;"></div>
    <div class="status-bar" id="statusBar"></div>
    <div class="card">
        <div class="card-title"><span>📦</span><span>Обновление из сетевой папки</span></div>
        <div class="step-row">
            <div class="step-num">1</div>
            <div class="step-body">
                <div class="step-title">Проверить обновления</div>
                <div class="step-desc">Найти новые патчи в сетевой папке, проверить целостность, прогнать dry-run. Изменения пока не вносятся.</div>
            </div>
            <button class="btn btn-secondary" id="btnCheck">🔍 Проверить</button>
        </div>
        <div class="check-result" id="checkResult" style="display:none;">
            <div class="check-result-title">📋 Результат проверки</div>
            <div id="checkBody"></div>
            <div id="logBody" style="display:none;">
                <div class="log-label">Вывод патчера (dry-run):</div>
                <div class="log-box" id="logBox"></div>
            </div>
        </div>
        <div class="step-row">
            <div class="step-num">2</div>
            <div class="step-body">
                <div class="step-title">Применить обновление</div>
                <div class="step-desc">Кнопка активна только после успешной проверки. Файлы будут изменены, бэкапы сохранены. Потребуется перезапуск сервера.</div>
            </div>
            <button class="btn btn-primary" id="btnApply" disabled>⬆ Применить</button>
        </div>
    </div>
    <div class="card">
        <div class="card-title"><span>↺</span><span>Откат патчей</span></div>
        <div class="rollback-hint">Если после обновления что-то сломалось — найдите нужный патч в <b>реестре ниже</b> и нажмите <b>«Откатить»</b>. Файлы будут восстановлены из бэкапов, версия пересчитается автоматически. Если от патча зависят применённые патчи выше — будет запрошено подтверждение.</div>
    </div>
    <div class="card">
        <div class="card-title"><span>📜</span><span>Реестр применённых патчей</span><span class="cnt" id="journalCnt">0</span></div>
        <div id="journalBody"><div class="loading">Загрузка…</div></div>
    </div>
</div>
<div class="modal-overlay" id="updaterCheckModal">
    <div class="modal-box updater-check-box">
        <h2 class="warn updater-check-title">
            <span style="font-size:1.7rem;">⬆</span> Доступно обновление
        </h2>
        <div class="updater-check-scroll" id="ucBody"></div>
        <div class="updater-check-footer">
            <label class="updater-check-auto">
                <input type="checkbox" id="ucAutoUpdate">
                <span>Автоматически устанавливать обновления без подтверждения</span>
            </label>
            <div class="modal-actions">
                <button class="btn btn-secondary" id="ucCancelBtn">Не сейчас</button>
                <button class="btn btn-primary" id="ucApplyBtn">Обновить сейчас</button>
            </div>
        </div>
    </div>
</div>

<div class="modal-overlay" id="restartModal">
    <div class="modal-box">
        <h2 class="ok" id="modalTitle">
            <span class="modal-icon" id="modalIcon">✅</span>
            <span id="modalTitleText">Готово</span>
        </h2>
        <div class="modal-body" id="modalBody"></div>
        <div class="modal-actions" id="modalActions">
            <button class="btn btn-primary" data-close="1">Понятно</button>
        </div>
    </div>
</div>
<script>
(function(){
'use strict';
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function _csrf(){ var t = window.REESTR_CSRF || ''; if (!t) { var m = document.querySelector('meta[name="csrf-token"]'); if (m) t = m.getAttribute('content') || ''; } return t; }

function showModal(kind, title, html, actionsHtml){
    var m = document.getElementById('restartModal');
    var h2 = document.getElementById('modalTitle');
    var ic = document.getElementById('modalIcon');
    var tt = document.getElementById('modalTitleText');
    h2.className = kind;
    ic.textContent = kind === 'ok' ? '✅' : (kind === 'err' ? '❌' : '⚠');
    tt.textContent = title;
    document.getElementById('modalBody').innerHTML = html;
    var actions = document.getElementById('modalActions');
    if (actionsHtml) {
        actions.innerHTML = actionsHtml;
    } else {
        actions.innerHTML = '<button class="btn btn-primary" data-close="1">Понятно</button>';
    }
    m.classList.add('active');
}

function renderBanner(d){
    var el = document.getElementById('versionBanner');
    var status = d.status || 'unknown';
    var cls = 'info', icon = 'ℹ';
    if (status === 'actual') { cls = 'ok'; icon = '✅'; }
    else if (status === 'available') { cls = 'warn'; icon = '⬆'; }
    var local = d.chain_version || d.version || '?';
    var remote = d.remote_version || '';
    var same = !remote || local === remote;
    var versions = same
        ? '<div class="vb-versions"><span class="vlocal">' + esc(local) + '</span></div>'
        : '<div class="vb-versions"><span class="vlocal">' + esc(local) + '</span>'
        + '<span class="arrow">→</span>'
        + '<span class="vremote">' + esc(remote) + '</span></div>';
    el.innerHTML = '<div class="version-banner ' + cls + '">'
        + '<div class="vb-icon">' + icon + '</div>'
        + '<div><div class="vb-title">Текущая версия программы</div>'
        + '<div class="vb-sub">' + esc(d.status_text || '') + '</div></div>'
        + versions
        + '<button class="vb-refresh" id="btnRefresh" title="Перечитать статус">🔄</button>'
        + '</div>';
    var btn = document.getElementById('btnRefresh');
    if (btn) btn.addEventListener('click', function(){ loadStatus(true); });
}

function renderStatus(d){
    var bar = document.getElementById('statusBar');
    // PATCH v1.0.11: битый журнал — громкая плашка, apply/rollback заблокированы.
    if (d && d.journal_corrupt) {
        bar.innerHTML = '<div class="stat-card err" style="grid-column: 1 / -1;">'
            + '<div class="v" style="font-size:0.85rem;line-height:1.35;">⚠ ' + esc(d.journal_error || 'журнал повреждён') + '</div>'
            + '<div class="l">Применение и откат заблокированы · восстановите из .patches_applied.archive-*.json</div>'
            + '</div>';
        var _bchk = document.getElementById('btnCheck');
        if (_bchk) _bchk.disabled = true;
        var _bapp = document.getElementById('btnApply');
        if (_bapp) _bapp.disabled = true;
        return;
    }
    var shareCls = d.share_ok ? 'ok' : 'err';
    var shareVal = d.share_ok ? 'доступна' : 'нет';
    var pending = (d.pending || []).length;
    var pendingCls = pending > 0 ? 'warn' : 'ok';
    var pendingVal = pending > 0 ? (pending + ' к применению') : 'нет';
    bar.innerHTML = ''
        + '<div class="stat-card"><div class="v">' + (d.applied_count || 0) + '</div><div class="l">Применено патчей</div></div>'
        + '<div class="stat-card ' + shareCls + '"><div class="v">' + esc(shareVal) + '</div><div class="l">Сетевая папка</div></div>'
        + '<div class="stat-card ' + pendingCls + '"><div class="v">' + esc(pendingVal) + '</div><div class="l">Обновления</div></div>'
        + '<div class="stat-card info"><div class="v">' + esc(d.chain_version || d.version || '—') + '</div><div class="l">Версия цепочки</div></div>';
    if (d.share_error) {
        var c = document.createElement('div');
        c.className = 'stat-card err';
        c.innerHTML = '<div class="v" style="font-size:0.75rem;">' + esc(d.share_error) + '</div><div class="l">Ошибка сети</div>';
        bar.appendChild(c);
    }
}

function renderCheck(data){
    var wrap = document.getElementById('checkResult');
    var el = document.getElementById('checkBody');
    wrap.style.display = '';
    var pending = data.pending || [];
    var verified = data.verified || [];
    if (!data.share_ok) {
        el.innerHTML = '<div class="empty" style="color:var(--pg-err);">' + esc(data.share_error || 'нет доступа') + '</div>';
        return;
    }
    if (!pending.length) {
        el.innerHTML = '<div class="empty" style="color:var(--pg-ok);">✅ Всё актуально, обновлений нет</div>';
        return;
    }
    var okCount = verified.filter(function(v){ return v.ok; }).length;
    var failCount = verified.length - okCount;
    var html = '<div style="font-size:0.85rem;color:var(--pg-meta);margin-bottom:10px;">'
        + 'Найдено <b style="color:var(--pg-accent);">' + pending.length + '</b> патч(ей)';
    if (failCount > 0) {
        html += ', из них <b style="color:var(--pg-err);">' + failCount + '</b> с ошибками';
    }
    html += '</div>';
    var skipped = data.skipped_files || [];
    if (skipped.length) {
        html += '<div style="margin:8px 0;padding:8px 10px;background:rgba(231,76,60,0.08);border-left:3px solid var(--pg-err);border-radius:8px;">'
             + '<div style="font-size:0.75rem;font-weight:800;color:var(--pg-err);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px;">⚠ Пропущенные файлы (' + skipped.length + ')</div>';
        skipped.forEach(function(s){
            html += '<div style="font-size:0.78rem;color:var(--pg-desc);padding:2px 0;word-break:break-word;"><b>' + esc(s.file) + '</b> — ' + esc(s.reason) + '</div>';
        });
        html += '</div>';
    }
    verified.forEach(function(v){
        var cls = v.ok ? (v.warning ? 'warn' : 'ok') : 'err';
        var ico = v.ok ? (v.warning ? '⚠' : '✓') : '✗';
        var meta = data.pending.find(function(p){ return p.id === v.id; }) || {};
        var verInfo = '';
        if (meta.requires_version || meta.target_version) {
            verInfo = '<div class="ver">'
                + (meta.requires_version ? 'требует ≥ ' + esc(meta.requires_version) : '')
                + (meta.requires_version && meta.target_version ? ' · ' : '')
                + (meta.target_version ? '→ ' + esc(meta.target_version) : '')
                + '</div>';
        }
        var descInfo = meta.description ? '<div class="desc">' + esc(meta.description) + '</div>' : '';
        html += '<div class="patch-row ' + cls + '">'
             + '<span class="ico">' + ico + '</span>'
             + '<div><div class="id">' + esc(v.id) + '</div>'
             + descInfo
             + verInfo
             + (v.warning ? '<div class="warn-msg">⚠ ' + esc(v.warning) + '</div>' : '')
             + (v.error ? '<div class="err-msg">✗ ' + esc(v.error) + '</div>' : '')
             + '</div></div>';
    });
    el.innerHTML = html;
    var allOk = verified.every(function(v){ return v.ok; });
    var dry = data.dry_run || {};
    document.getElementById('btnApply').disabled = !allOk || !dry.rc_ok || !window.UPDATER_CAN_APPLY;
    if (dry.output) {
        document.getElementById('logBody').style.display = '';
        document.getElementById('logBox').textContent = dry.output;
    } else if (!allOk) {
        document.getElementById('logBody').style.display = '';
        document.getElementById('logBox').textContent = 'Патчер не запущен: сначала исправьте ошибки в патчах.';
    }
}

function renderChainWarning(d){
    var el = document.getElementById('chainWarn');
    if (!el) return;
    var miss = d.missing_ids || [];
    if (!miss.length) { el.style.display = 'none'; el.innerHTML = ''; return; }
    el.style.display = '';
    el.innerHTML = '<div class="chain-warn">'
        + '<div class="chain-warn-title">⚠ В цепочке патчей есть пропуски</div>'
        + '<div class="chain-warn-body">'
        + '<p>Не установлены зависимые патчи: <b>' + miss.map(esc).join(', ') + '</b>.</p>'
        + '<p>Версия программы показывает только непрерывный префикс: <b>v' + esc(d.chain_version || d.version || '?') + '</b>.</p>'
        + '<p>Последний физически применённый патч: <b>' + esc(d.last_applied_id || '—') + '</b> (v' + esc(d.last_applied_version || '?') + ').</p>'
        + '<p style="margin-top:6px;color:var(--pg-meta);">Рекомендуется применить пропущенные патчи — они появятся в списке ниже.</p>'
        + '</div></div>';
}

function renderJournal(items){
    var el = document.getElementById('journalBody');
    document.getElementById('journalCnt').textContent = items.length;
    if (!items.length) {
        el.innerHTML = '<div class="empty">Патчей ещё не применялось</div>';
        return;
    }
    var h = '<table class="journal-table"><thead><tr>'
          + '<th style="width:70px;">Версия</th>'
          + '<th>ID / Описание</th>'
          + '<th style="width:70px;">Время</th>'
          + '<th class="num" style="width:50px;">Оп.</th>'
          + '<th style="width:90px;"></th>'
          + '</tr></thead><tbody>';
    var lastDay = '';
    items.forEach(function(p){
        var day = (p.applied_at || '').slice(0, 10);
        if (day !== lastDay) {
            h += '<tr class="day-sep"><td colspan="5">' + esc(day) + '</td></tr>';
            lastDay = day;
        }
        var ver = p.version || '—';
        var verCls = p.version ? 'ver-pill' : 'ver-none';
        var desc = (p.description || '').replace(/\s+/g, ' ').trim();
        h += '<tr data-id="' + esc(p.id) + '">'
           + '<td><span class="' + verCls + '">' + esc(ver) + '</span></td>'
           + '<td><div class="j-id">' + esc(p.id) + '</div>'
           +      (desc ? '<div class="j-desc">' + esc(desc) + '</div>' : '')
           + '</td>'
           + '<td class="muted">' + esc((p.applied_at || '').slice(11, 19)) + '</td>'
           + '<td class="num">' + (p.ops || 0) + '</td>'
           + '<td class="actions">' + (window.UPDATER_CAN_APPLY ? '<button class="btn btn-danger" data-rollback="' + esc(p.id) + '">↺ Откатить</button>' : '') + '</td>'
           + '</tr>';
    });
    h += '</tbody></table>';
    el.innerHTML = h;
    el.querySelectorAll('[data-rollback]').forEach(function(b){
        b.addEventListener('click', function(){ doRollback(this.getAttribute('data-rollback')); });
    });
}

function loadStatus(showSpin){
    var btn = document.getElementById('btnRefresh');
    if (showSpin && btn) btn.classList.add('spin');
    fetch('/api/plugins/updater/status', {credentials: 'same-origin'})
        .then(function(r){
            if (!r.ok) {
                return r.text().then(function(t){
                    var msg = 'HTTP ' + r.status;
                    try { var j = JSON.parse(t); if (j && j.error) msg += ' — ' + j.error; if (j && j.hint) msg += ' (' + j.hint + ')'; } catch (e) {}
                    throw new Error(msg);
                });
            }
            return r.json();
        })
        .then(function(d){
            if (!d.success) return;
            renderBanner(d);
            renderStatus(d);
            renderChainWarning(d);
            renderJournal(d.journal || []);
        })
        .catch(function(){})
        .finally(function(){
            var b = document.getElementById('btnRefresh');
            if (b) b.classList.remove('spin');
        });
}

var _settings = { auto_update: false };
function _loadSettings() {
    return fetch('/api/plugins/updater/settings', {credentials: 'same-origin'})
        .then(function(r){ return r.json(); })
        .then(function(d){
            if (d && d.success) {
                _settings.auto_update = d.auto_update;
                var cb = document.getElementById('ucAutoUpdate');
                if (cb) cb.checked = d.auto_update;
            }
        }).catch(function(){});
}

function showUpdateFound(d) {
    var body = document.getElementById('ucBody');
    var html = '<p>Найдены новые патчи, которые можно применить:</p><ul style="margin:10px 0 0 20px; font-size:0.85rem; line-height:1.5;">';
    (d.pending || []).forEach(function(p) {
        html += '<li><b>' + esc(p.id) + '</b> — ' + esc(p.description || 'Нет описания') + '</li>';
    });
    html += '</ul>';
    body.innerHTML = html;
    
    var modal = document.getElementById('updaterCheckModal');
    modal.classList.add('active');
    
    document.getElementById('ucApplyBtn').onclick = function() {
        modal.classList.remove('active');
        doApply(false);
    };
    document.getElementById('ucCancelBtn').onclick = function() {
        modal.classList.remove('active');
    };
}

document.getElementById('ucAutoUpdate').addEventListener('change', function(){
    var val = this.checked;
    _settings.auto_update = val;
    fetch('/api/plugins/updater/settings', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrf()},
        body: JSON.stringify({auto_update: val})
    }).catch(function(){});
});

function doCheck(isAutoCheck){
    var btn = document.getElementById('btnCheck');
    if (!isAutoCheck && btn) {
        btn.disabled = true;
        document.getElementById('checkResult').style.display = '';
        document.getElementById('checkBody').innerHTML = '<div class="loading">Проверка…</div>';
        document.getElementById('logBody').style.display = 'none';
        document.getElementById('btnApply').disabled = true;
    }
    fetch('/api/plugins/updater/check', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': _csrf() },
    })
    .then(function(r){
        var ct = r.headers.get('content-type') || '';
        if (ct.indexOf('application/json') === -1) {
            return r.text().then(function(t){ throw new Error('HTTP ' + r.status + ': ' + t.slice(0, 200)); });
        }
        return r.json();
    })
    .then(function(d){
        if (!isAutoCheck && btn) btn.disabled = false;
        if (!d.success) {
            if (!isAutoCheck) document.getElementById('checkBody').innerHTML = '<div class="empty" style="color:var(--pg-err);">✗ ' + esc(d.error || 'ошибка') + '</div>';
            return;
        }
        renderCheck(d);
        renderBanner(d);
        renderStatus(d);
        renderChainWarning(d);

        if (d.pending && d.pending.length > 0) {
            var allOk = (d.verified || []).every(function(v) { return v.ok; });
            var dryOk = d.dry_run && d.dry_run.rc_ok;
            
            if (_settings.auto_update && allOk && dryOk) {
                showModal('warn', 'Автообновление', '<p>Найдены обновления. Запуск установки...</p><div style="text-align:center;padding:20px;"><span class="up-spinner"></span></div>');
                setTimeout(function(){ doApply(true); }, 1000);
            } else {
                showUpdateFound(d);
            }
        }
    })
    .catch(function(e){
        btn.disabled = false;
        document.getElementById('checkBody').innerHTML = '<div class="empty" style="color:var(--pg-err);">✗ ' + esc(e.message) + '</div>';
    });
}

function doApply(silent){
    if (!silent && !confirm('Применить обновление?\n\nПатчи будут внесены в файлы проекта.\nПосле применения потребуется перезагрузить сервер.')) return;
    var btn = document.getElementById('btnApply');
    if (!silent && btn) btn.disabled = true;
    if (!silent) document.getElementById('checkBody').innerHTML = '<div class="loading">Применение…</div>';
    fetch('/api/plugins/updater/apply', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': window.REESTR_CSRF || '' },
    })
    .then(function(r){
        var ct = r.headers.get('content-type') || '';
        if (ct.indexOf('application/json') === -1) {
            return r.text().then(function(t){ throw new Error('HTTP ' + r.status + ': ' + t.slice(0, 300)); });
        }
        return r.json();
    })
    .then(function(d){
        if (!d.success) {
            showModal('err', 'Ошибка применения', '<p>' + esc(d.error || '') + '</p>'
                + (d.output ? '<div class="log-box">' + esc(d.output) + '</div>' : ''));
            return;
        }
        if (silent) {
            showModal('warn', 'Сервер перезагружается', '<p>Обновление применено. Ожидайте восстановления соединения...</p><div style="text-align:center;padding:20px;"><span class="up-spinner"></span></div>');
            _doRestart();
        } else {
            showModal('ok', 'Обновление применено',
                '<p>Применено патчей: <span class="hl">' + (d.applied_count || 0) + '</span></p>'
                + '<p>Новая версия: <span class="hl">' + esc(d.new_version || '?') + '</span></p>'
                + '<p style="margin-top:14px;">Файлы обновлены. Для применения изменений необходимо перезагрузить сервер.</p>',
                '<button class="btn btn-primary" id="btnRestartServer">🔄 Перезагрузить сервер</button>');
            loadStatus();
        }
    })
    .catch(function(e){
        document.getElementById('checkBody').innerHTML = '<div class="empty" style="color:var(--pg-err);">✗ ' + esc(e.message) + '</div>';
    });
}

function doRollback(pid, force){
    if (!force && !confirm('Откатить патч «' + pid + '»?\n\nФайлы будут восстановлены из бэкапов.\nСозданные патчем файлы будут удалены.')) return;
    showModal('warn', 'Откат патча…', '<p style="text-align:center;padding:18px;"><span class="up-spinner"></span></p><p style="text-align:center;color:var(--pg-meta);">Восстанавливаем файлы</p>');
    var _cb = document.getElementById('btnCloseModal');
    if (_cb) _cb.style.display = 'none';
    var _rc = function(){ if (_cb) _cb.style.display = ''; };
    var payload = { id: pid };
    if (force) payload.force = true;
    fetch('/api/plugins/updater/rollback', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': window.REESTR_CSRF || '' },
        body: JSON.stringify(payload),
    })
    .then(function(r){
        if (r.status === 409) {
            return r.json().then(function(d){
                if (d && d.need_force && Array.isArray(d.dependents) && d.dependents.length) {
                    // PATCH v1.0.15: показываем причину зависимости.
                    var _lines = [];
                    var _details = d.dependents_details || [];
                    if (_details.length) {
                        _details.forEach(function(x){
                            if (x.reason === 'requires')
                                _lines.push('• ' + x.id + ' — требует «' + pid + '»');
                            else
                                _lines.push('• ' + x.id + ' — общий файл: ' + (x.files || []).join(', '));
                        });
                    } else {
                        _lines = d.dependents.map(function(x){ return '• ' + x; });
                    }
                    var msg = 'От патча «' + pid + '» зависят применённые позже патчи:\n\n'
                            + _lines.join('\n')
                            + '\n\nВсё равно откатить? Зависимые будут откачены ПЕРВЫМИ '
                            + '(в порядке убывания версии), чтобы не порвать цепочку.';
                    if (confirm(msg)) return doRollback(pid, true);
                    return { success: false, error: 'cancelled' };
                }
                return d;
            });
        }
        return r.json();
    })
    .then(function(d){
        if (!d || !d.success) {
            if (d && d.error === 'cancelled') return;
            showModal('err', 'Ошибка отката', '<p>' + esc((d && d.error) || '') + '</p>'
                + ((d && d.output) ? '<div class="log-box">' + esc(d.output) + '</div>' : ''));
            return;
        }
        showModal('ok', 'Патч откачен',
            '<p>Откачен патч: <span class="hl">' + esc(d.rolled_back || pid) + '</span></p>'
            + '<p>Новая версия: <span class="hl">' + esc(d.new_version || '?') + '</span></p>'
            + '<p style="margin-top:14px;">Файлы восстановлены. Для применения изменений необходимо перезагрузить сервер.</p>',
            '<button class="btn btn-primary" id="btnRestartServer">🔄 Перезагрузить сервер</button>');
        loadStatus();
    })
    .catch(function(e){
        showModal('err', 'Ошибка отката', '<p>' + esc(e.message) + '</p>');
    });
}

document.getElementById('btnCheck').addEventListener('click', doCheck);
document.getElementById('btnApply').addEventListener('click', doApply);
function _doRestart() {
    fetch('/api/settings/restart', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': _csrf() }
    }).then(function(r){ return r.json(); }).then(function(d){
        if (d.success) {
            var attempts = 0;
            var iv = setInterval(function(){
                attempts++;
                fetch('/login', {method: 'HEAD', cache: 'no-store'})
                    .then(function(){ clearInterval(iv); location.reload(); })
                    .catch(function(){
                        if (attempts > 20) {
                            clearInterval(iv);
                            showModal('err', 'Сервер остановлен', '<p>Пожалуйста, запустите <b>START.bat</b> заново.</p>');
                        }
                    });
            }, 1000);
        } else {
            alert('Ошибка: ' + (d.error || 'неизвестна'));
        }
    }).catch(function(err){
        alert('Ошибка соединения: ' + err.message);
    });
}

document.getElementById('restartModal').addEventListener('click', function(e){
    if (e.target === this || (e.target.closest && e.target.closest('[data-close="1"]'))) {
        this.classList.remove('active');
        return;
    }
    
    var btnRestart = e.target.closest && e.target.closest('#btnRestartServer');
    if (btnRestart) {
        btnRestart.disabled = true;
        btnRestart.textContent = '⏳ Перезагрузка...';
        _doRestart();
    }
});

_loadSettings().then(function(){
    doCheck(true);
});
loadStatus();

if (!window.UPDATER_CAN_APPLY) {
    var btnApplyEl = document.getElementById('btnApply');
    if (btnApplyEl) btnApplyEl.title = 'Нет права применять обновления';
}
})();
</script>
</body>
</html>'''


# ============================================================
# Регистрация
# ============================================================
def register(app, db, hooks):
    print('[updater] v' + __version__ + ' · ' + __description__)
    try:
        _read_version()
    except Exception as e:
        print(f'[updater] init version failed: {e}')

    @app.route('/api/plugins/updater/debug', methods=['GET'])
    def _up_debug():
        # PATCH v1.0.2: эндпоинт был открыт без авторизации.
        u = _auth_ok(db)
        if not u:
            return jsonify({'success': False, 'error': 'auth'}), 401
        share, err = _share_dir()
        if not share:
            return jsonify({'ok': False, 'share': None, 'err': err})
        out = {'ok': True, 'share_path': str(share), 'err': err}
        try:
            items = sorted([x.name for x in share.iterdir()])
            out['iterdir_count'] = len(items)
            out['iterdir_sample'] = items[:40]
        except Exception as e:
            out['iterdir_error'] = repr(e)
        try:
            js = sorted([x.name for x in share.glob('*.json')])
            out['glob_json_count'] = len(js)
            out['glob_json_sample'] = js[:40]
        except Exception as e:
            out['glob_json_error'] = repr(e)
        try:
            js2 = sorted([x.name for x in share.glob('**/*.json')])
            out['glob_recursive_count'] = len(js2)
            out['glob_recursive_sample'] = js2[:40]
        except Exception as e:
            out['glob_recursive_error'] = repr(e)
        try:
            files = []
            for f in share.glob('*.json'):
                try:
                    sz = f.stat().st_size
                except Exception:
                    sz = -1
                files.append({'name': f.name, 'size': sz})
            out['files_detail'] = files[:20]
        except Exception as e:
            out['files_detail_error'] = repr(e)
        try:
            _sk = []
            _p = _scan_patches(share, skipped_out=_sk)
            out['scan_patches_count'] = len(_p)
            out['scan_patches_ids'] = [x.get('id') for x in _p][:30]
            out['scan_patches_skipped'] = _sk[:20]
        except Exception as e:
            out['scan_patches_error'] = repr(e)
        return jsonify(out)

    @app.route('/api/plugins/updater/_diag', methods=['GET'])
    def _up_diag():
        # PATCH v1.0.2: эндпоинт был открыт без авторизации.
        u = _auth_ok(db)
        if not u:
            return jsonify({'success': False, 'error': 'auth'}), 401
        out = {'success': True}
        try:
            u = _auth_ok(db)
            out['auth_ok'] = bool(u)
            out['user'] = {'id': (u or {}).get('id'), 'username': (u or {}).get('username'), 'role': (u or {}).get('role')}
        except Exception as e: out['auth_error'] = repr(e)
        try:
            j = _read_journal()
            out['journal_path'] = str(JOURNAL_PATH)
            out['journal_exists'] = JOURNAL_PATH.exists()
            out['journal_len'] = len(j)
            out['journal_keys'] = list(j.keys())[:50]
            try: out['journal_table_len'] = len(_journal_table(j))
            except Exception as e: out['journal_table_error'] = repr(e)
        except Exception as e: out['journal_error'] = repr(e)
        try:
            share, err = _share_dir()
            out['share_path'] = str(share) if share else None
            out['share_ok'] = bool(share)
            out['share_error'] = err
        except Exception as e: out['share_dir_error'] = repr(e)
        try: out['version'] = _current_version()
        except Exception as e: out['version_error'] = repr(e)
        try:
            from app import create_app  # noqa: F401
            out['app_importable'] = True
        except Exception as e:
            out['app_importable'] = False
            out['app_import_error'] = repr(e)
        return jsonify(out)

    @app.route('/api/plugins/updater/version', methods=['GET'])
    def _up_version():
        try:
            from auth import current_user
            u = current_user(db)
            if not u:
                return jsonify({'success': False, 'error': 'auth'}), 401
            local_v = _current_version()
            remote = local_v
            has_update = False
            has_gaps = False
            missing_ids = []
            share, _ = _share_dir()
            if share:
                patches = _scan_patches(share)
                journal = _read_journal()                                # <-- переносим наверх
                ordered, _perr = _parse_patches_order(patches, journal.keys())
                if ordered:
                    try:
                        eff = _effective_version({'patches': ordered}, journal)

                        local_v = eff['chain_version']
                        missing_ids = eff['missing_ids']
                        has_gaps = bool(missing_ids)
                    except Exception:
                        has_gaps = False
                        missing_ids = []
                    pending = [p for p in ordered
                               if (p.get('id') or Path(p.get('file', '')).stem) not in journal]
                    if pending:
                        vers = [p.get('target_version') for p in pending if p.get('target_version')]
                        remote = max(vers, key=_ver_tuple) if vers else local_v
                        has_update = _ver_cmp(remote, local_v) > 0 or bool(pending)
            return jsonify({
                'success': True,
                'version': local_v,
                'has_gaps': has_gaps,
                'missing_ids': missing_ids,
                'remote_version': remote,
                'has_update': bool(has_update),
            })
        except Exception as e:
            traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/plugins-assets/updater.js', methods=['GET'])
    def _up_js():
        resp = app.response_class(_JS, mimetype='application/javascript')
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        return resp

    @app.route('/plugins/updater/', methods=['GET'])
    def _up_page():
        u = _auth_ok(db)
        if not u:
            return redirect('/login')
        try:
            from auth import ensure_csrf, user_has
            token = ensure_csrf() or ''
            can_apply = user_has(db, u, 'action.updater.apply')
        except Exception:
            token = ''
            can_apply = False
        html = _page_html().replace('__CSRF_TOKEN__', token).replace('__CAN_APPLY__', 'true' if can_apply else 'false')
        resp = Response(html, mimetype='text/html')
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp

    @app.route('/api/plugins/updater/status', methods=['GET'])
    def _up_status():
        try:
            u = _auth_ok(db)
            if not u:
                return jsonify({'success': False, 'error': 'forbidden', 'hint': 'Нет прав tab.updater'}), 403
            # PATCH v1.0.11: status возвращается даже при битом журнале —
            # но с явным флагом journal_corrupt, чтобы UI не молчал.
            _journal_corrupt = False
            _journal_error = ''
            try:
                journal = _read_journal_strict()
            except RuntimeError as _e:
                journal = {}
                _journal_corrupt = True
                _journal_error = str(_e)
            share, share_err = _share_dir()
            st = _status(share, journal)
            if share_err and not st.get('share_error'):
                st['share_error'] = share_err
            st['_diag_ok'] = True
            st['_diag_journal_len'] = len(journal)
            st['journal_corrupt'] = _journal_corrupt
            st['journal_error'] = _journal_error
            st['success'] = True
            return jsonify(st)
        except Exception as e:
            traceback.print_exc()
            return jsonify({'success': False, 'error': f'status failed: {e}', '_diag_error': repr(e)}), 500

    def _cleanup_staging(keep=10):
        try:
            if not STAGE_ROOT.exists():
                return
            dirs = sorted([d for d in STAGE_ROOT.iterdir() if d.is_dir()],
                          key=lambda x: x.stat().st_mtime, reverse=True)
            for old in dirs[keep:]:
                try:
                    shutil.rmtree(old)
                except Exception:
                    pass
        except Exception as e:
            print(f'[updater] staging cleanup failed: {e}')

    def _cleanup_backups(keep=20):
        try:
            bdir = PROJECT_DIR / 'patch_backups'
            if not bdir.exists():
                return
            baks = sorted(bdir.rglob('*.bak-*'),
                          key=lambda x: x.stat().st_mtime, reverse=True)
            for old in baks[keep:]:
                try:
                    old.unlink()
                except Exception:
                    pass
        except Exception as e:
            print(f'[updater] backups cleanup failed: {e}')

    @app.route('/api/plugins/updater/settings', methods=['GET'])
    def _up_get_settings():
        try:
            u = _auth_ok(db)
            if not u: return jsonify({'success': False, 'error': 'forbidden'}), 403
            auto = db.get_setting('updater_auto_update', '0')
            return jsonify({'success': True, 'auto_update': auto == '1'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/plugins/updater/settings', methods=['POST'])
    def _up_set_settings():
        try:
            u = _auth_ok(db)
            if not u: return jsonify({'success': False, 'error': 'forbidden'}), 403
            body = request.get_json() or {}
            val = '1' if body.get('auto_update') else '0'
            db.set_setting('updater_auto_update', val)
            return jsonify({'success': True, 'auto_update': val == '1'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/plugins/updater/check', methods=['POST'])
    def _up_check():
        try:
            u = _auth_ok(db)
            if not u:
                return jsonify({'success': False, 'error': 'forbidden'}), 403
            # PATCH v1.0.11: strict reader — битый журнал блокирует проверку.
            try:
                journal = _read_journal_strict()
            except RuntimeError as _e:
                return jsonify({'success': False, 'error': str(_e)}), 500
            local_v = _current_version()
            share, share_err = _share_dir()
            if not share:
                return jsonify({'success': False, 'error': share_err or 'сеть недоступна'}), 400
            st = _status(share, journal)
            ordered, pending, perr = _collect_pending(share, journal, local_v)
            if perr:
                return jsonify({'success': False, 'error': perr}), 400
            # PATCH 1.0.11: пересчитываем skipped_files в отчёте Check
            _skipped2 = []
            _scan_patches(share, skipped_out=_skipped2)
            st['skipped_files'] = _skipped2
            st['verified'] = _verify_patches(share, pending, local_v)
            ok_pending = [p for p, v in zip(pending, st['verified']) if v['ok']]
            dry = {'rc_ok': False, 'output': ''}
            all_ok = all(v['ok'] for v in st['verified'])
            if ok_pending:
                ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:21]
                try:
                    stage = _stage(share, ok_pending, ts)
                    rc, out = _run_patcher(stage, dry=True, timeout=180)
                    dry['rc'] = rc
                    dry['rc_ok'] = (rc == 0 and all_ok)
                    dry['output'] = out
                except Exception as e:
                    dry['output'] = f'ошибка stage: {e}'
                    traceback.print_exc()
            st['dry_run'] = dry
            st['success'] = True
            return jsonify(st)
        except Exception as e:
            traceback.print_exc()
            return jsonify({'success': False, 'error': f'check failed: {e}'}), 500

    @app.route('/api/plugins/updater/apply', methods=['POST'])
    def _up_apply():
        lock = _UpdaterLock(LOCK_PATH)
        if not lock.acquire():
            return jsonify({
                'success': False,
                'error': 'Другое обновление уже выполняется. Повторите позже.',
            }), 409
        try:
            u = _auth_ok(db, need_apply=True)
            if not u:
                return jsonify({'success': False, 'error': 'forbidden'}), 403
            # PATCH v1.0.11: strict reader — при повреждённом журнале
            # применение заблокировано.
            try:
                journal = _read_journal_strict()
            except RuntimeError as _e:
                return jsonify({'success': False, 'error': str(_e)}), 500
            local_v = _current_version()
            share, share_err = _share_dir()
            if not share:
                return jsonify({'success': False, 'error': share_err or 'сеть недоступна'}), 400
            ordered, pending, perr = _collect_pending(share, journal, local_v)
            if perr:
                return jsonify({'success': False, 'error': perr}), 400
            if not pending:
                return jsonify({'success': False, 'error': 'нечего применять'}), 400

            verified = _verify_patches(share, pending, local_v)
            bad = [v for v in verified if not v['ok']]
            if bad:
                return jsonify({
                    'success': False,
                    'error': 'провалена проверка: ' + '; '.join(v['error'] for v in bad),
                }), 400

            ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:21]
            try:
                stage = _stage(share, pending, ts)
            except Exception as e:
                traceback.print_exc()
                return jsonify({'success': False, 'error': f'ошибка stage: {e}'}), 500

            dry_rc, dry_out = _run_patcher(stage, dry=True, timeout=180)
            if dry_rc != 0:
                return jsonify({'success': False, 'error': 'dry-run не прошёл', 'output': dry_out}), 400

            # PATCH v1.0.7: журнал ДО apply — чтобы точно знать, что применилось.
            journal_before_apply = set(_read_journal().keys())

            apply_rc, apply_out = _run_patcher(stage, dry=False, timeout=300)

            journal_now = _read_journal()
            applied_now = [pid for pid in journal_now if pid not in journal_before_apply]
            not_applied = [p.get('id') for p in pending if p.get('id') not in journal_now]

            new_v = _current_version()
            try:
                share2, _ = _share_dir()
                if share2:
                    _p2 = _scan_patches(share2)
                    _o2, _ = _parse_patches_order(_p2, _read_journal().keys())
                    if _o2:
                        new_v = _recompute_version_from_manifest({'patches': _o2})
            except Exception as _e:
                print(f'[updater] version recompute failed: {_e}')

            if apply_rc != 0:
                # PATCH v1.0.7: возвращаем applied_ids и not_applied_ids,
                # чтобы UI показал пользователю, что именно применилось.
                return jsonify({
                    'success': False,
                    'error': f'патчер вернул код {apply_rc}',
                    'output': apply_out,
                    'applied_ids': applied_now,
                    'not_applied_ids': not_applied,
                    'new_version': new_v,
                }), 500

            try:
                from app import _audit as _app_audit
                _app_audit(db, u, 'update', 'project', new_v, {
                    'applied': [p.get('id') or p.get('file') for p in pending],
                    'from_version': local_v,
                    'to_version': new_v,
                })
            except Exception as e:
                print(f'[updater] audit failed: {e}')

            # PATCH v1.0.6: подчищаем staging и старые бэкапы после apply.
            try:
                _cleanup_staging(keep=10)
                _cleanup_backups(keep=20)
            except Exception as _e_cl:
                print(f'[updater] cleanup after apply failed: {_e_cl}')
            return jsonify({
                'success': True,
                'applied_count': len(pending),
                'total_count': len(pending),
                'new_version': new_v,
                'output': apply_out,
            })
        except Exception as e:
            traceback.print_exc()
            return jsonify({'success': False, 'error': f'apply failed: {e}'}), 500
        finally:
            lock.release()

    @app.route('/api/plugins/updater/rollback', methods=['POST'])
    def _up_rollback():
        lock = _UpdaterLock(LOCK_PATH)
        if not lock.acquire():
            return jsonify({
                'success': False,
                'error': 'Другое обновление уже выполняется. Повторите позже.',
            }), 409
        try:
            u = _auth_ok(db, need_apply=True)
            if not u:
                return jsonify({'success': False, 'error': 'forbidden'}), 403

            body = request.get_json() or {}
            pid = str(body.get('id', '')).strip()
            force = bool(body.get('force'))
            if not pid:
                return jsonify({'success': False, 'error': 'не указан id'}), 400

            # PATCH v1.0.11: strict reader — битый журнал блокирует откат.
            try:
                journal = _read_journal_strict()
            except RuntimeError as _e:
                return jsonify({'success': False, 'error': str(_e)}), 500
            if pid not in journal:
                return jsonify({'success': False, 'error': f'патч «{pid}» не найден в журнале'}), 404

            share, _share_err = _share_dir()
            if not share:
                # PATCH v1.0.9: без share нельзя проверить зависимости,
                # откат может оставить зависимые патчи в журнале.
                return jsonify({
                    'success': False,
                    'error': f'Сетевая папка недоступна ({_share_err}). Откат запрещён без проверки зависимостей.',
                }), 400

            # PATCH v1.0.9 + v1.0.15: собираем зависимые патчи.
            # v1.0.15: по общим файлам зависимый — только применённый ПОЗЖЕ.
            # Раньше любой патч, трогавший те же файлы, считался зависимым,
            # и откат блокировался без причины (12 мешал откату 13, 13 — откату 12).
            _all = _scan_patches(share)
            _my_files = set()
            for _p in _all:
                if _p.get('id') == pid:
                    for _op in (_p.get('operations') or []):
                        _f = _op.get('path') or _op.get('src') or ''
                        if _f:
                            _my_files.add(_f)
                    break
            _my_applied_at = (journal.get(pid) or {}).get('applied_at') or ''
            dependents = []
            dependents_details = []  # PATCH v1.0.15
            _dep_set = set()
            for _p in _all:
                _id = _p.get('id')
                if not _id or _id == pid:
                    continue
                if _id not in journal:
                    continue
                _reqs = _p.get('requires') or []
                if pid in _reqs:
                    if _id not in _dep_set:
                        _dep_set.add(_id)
                        dependents.append(_id)
                        dependents_details.append({
                            'id': _id, 'reason': 'requires', 'files': [],
                        })
                    continue
                # по общим файлам — только если применён ПОЗЖЕ
                _other_applied_at = (journal.get(_id) or {}).get('applied_at') or ''
                if not _other_applied_at or not _my_applied_at:
                    continue  # нет данных о времени — не блокируем
                if _other_applied_at <= _my_applied_at:
                    continue  # применён раньше или одновременно — не зависимый
                _shared = []
                for _op in (_p.get('operations') or []):
                    _f = _op.get('path') or _op.get('src') or ''
                    if _f and _f in _my_files and _f not in _shared:
                        _shared.append(_f)
                if _shared:
                    if _id not in _dep_set:
                        _dep_set.add(_id)
                        dependents.append(_id)
                        dependents_details.append({
                            'id': _id, 'reason': 'shared_file', 'files': _shared,
                        })
            if dependents and not force:
                _dep_list = []
                for _d in dependents_details:
                    if _d['reason'] == 'requires':
                        _dep_list.append(f"{_d['id']} (требует «{pid}»)")
                    else:
                        _dep_list.append(f"{_d['id']} (общие файлы: {', '.join(_d['files'])})")
                return jsonify({
                    'success': False,
                    'error': f"От патча «{pid}» зависят применённые позже патчи: " + '; '.join(_dep_list),
                    'dependents': dependents,
                    'dependents_details': dependents_details,
                    'need_force': True,
                }), 409

            # PATCH v1.0.9: при force=True сначала откатываем зависимые
            # в порядке убывания версии, потом сам патч.
            rolled_back_deps = []
            if dependents and force:
                def _vkey(_pid):
                    _info = journal.get(_pid, {})
                    _v = (_info.get('target_version') or '').strip()
                    try:
                        import re as _re_rb
                        _parts = _v.split('.')
                        _out = []
                        for _p in _parts[:3]:
                            _m = _re_rb.match(r'(\d+)', _p)
                            _out.append(int(_m.group(1)) if _m else 0)
                        while len(_out) < 3:
                            _out.append(0)
                        return tuple(_out)
                    except Exception:
                        return (0, 0, 0)
                for _dep in sorted(dependents, key=_vkey, reverse=True):
                    try:
                        _rc_d, _out_d = _run_patcher_rollback(_dep, timeout=120)
                        if _rc_d != 0:
                            return jsonify({
                                'success': False,
                                'error': f'не удалось откатить зависимый патч {_dep}',
                                'output': _out_d,
                                'rolled_back_deps': rolled_back_deps,
                            }), 500
                        rolled_back_deps.append(_dep)
                    except Exception as _e:
                        return jsonify({
                            'success': False,
                            'error': f'исключение при откате {_dep}: {_e}',
                            'rolled_back_deps': rolled_back_deps,
                        }), 500

            rc, out = _run_patcher_rollback(pid)
            if rc != 0:
                # PATCH v1.0.8: при rc != 0 файлы могли не восстановиться
                # (см. patcher.rollback). Патч НЕ удаляется из журнала.
                return jsonify({
                    'success': False,
                    'error': f'патчер вернул код {rc}: файлы могли не восстановиться, патч оставлен в журнале',
                    'output': out,
                }), 500

            new_v = _current_version()
            if share:
                patches = _scan_patches(share)
                ordered, _ = _parse_patches_order(patches, _read_journal().keys())
                if ordered:
                    new_v = _recompute_version_from_manifest({'patches': ordered})

            try:
                from app import _audit as _app_audit
                _app_audit(db, u, 'rollback', 'patch', pid, {'new_version': new_v})
            except Exception as e:
                print(f'[updater] audit failed: {e}')

            # PATCH v1.0.6: подчищаем staging и старые бэкапы после rollback.
            try:
                _cleanup_staging(keep=10)
                _cleanup_backups(keep=20)
            except Exception as _e_cl:
                print(f'[updater] cleanup after rollback failed: {_e_cl}')
            return jsonify({
                'success': True,
                'rolled_back': pid,
                'rolled_back_deps': rolled_back_deps,
                'new_version': new_v,
                'output': out,
            })
        except Exception as e:
            traceback.print_exc()
            return jsonify({'success': False, 'error': f'rollback failed: {e}'}), 500
        finally:
            lock.release()

    def on_startup(**ctx):
        print('[updater] готов — /plugins/updater/')

    hooks.on('on_startup', on_startup)
