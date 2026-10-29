#!/usr/bin/env python3
"""
patcher.py v4 — патчер с корректным chained dry-run.

Использование
-------------
    python patcher.py patches/                # применить все *.json из папки
    python patcher.py patch.json              # применить один
    python patcher.py patches/ --dry          # цепочка в памяти, без записи
    python patcher.py patches/ --force        # переприменить уже применённые
    python patcher.py patches/ --no-backup    # без .bak-файлов
    python patcher.py --only <id>             # только один патч из папки
    python patcher.py --applied               # список применённых
    python patcher.py --rollback <id>         # откатить патч по id
    python patcher.py --migrate-backups       # перенести старые .bak-* в patch_backups/
    python patcher.py --list-ops              # справка по операциям

Ключевое отличие v4 от v3
-------------------------
В --dry весь вывод пишется в overlay-словарь, а не на диск. Все операции
при чтении сначала смотрят в overlay, потом на диск. Значит, цепочка
зависимых патчей (v1.0.8 → v1.0.9 → ...) корректно проверяется: каждый
следующий патч видит файлы уже с учётом предыдущих. Именно этого не
хватало, чтобы updater активировал кнопку «Применить».

Порядок применения задаётся не именем файла, а полем target_version
плюс графом requires.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).parent.resolve()
JOURNAL = '.patches_applied.json'
BACKUP_DIR_NAME = 'patch_backups'
SEARCH_DIRS = (
    'static', 'src', 'app', 'scripts', 'tools',
    'templates', 'js', 'css', 'public', 'assets',
)


# ============================================================
# ЦВЕТА
# ============================================================
class C:
    OK = '\033[92m'
    ERR = '\033[91m'
    WARN = '\033[93m'
    INFO = '\033[94m'
    DIM = '\033[2m'
    BOLD = '\033[1m'
    END = '\033[0m'

    @staticmethod
    def off():
        for k in ('OK', 'ERR', 'WARN', 'INFO', 'DIM', 'BOLD', 'END'):
            setattr(C, k, '')


if not sys.stdout.isatty():
    C.off()

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


# ============================================================
# VFS-OVerlay для dry-run
# ============================================================
_VFS: dict[str, str] = {}
_VFS_DELETED: set[str] = set()


def _vfs_reset() -> None:
    _VFS.clear()
    _VFS_DELETED.clear()


def _vfs_active() -> bool:
    return bool(_VFS) or bool(_VFS_DELETED)


def _abs(p: Path) -> str:
    try:
        return str(p.resolve())
    except Exception:
        return str(p)


def _vfs_set(path: Path, content: str) -> None:
    k = _abs(path)
    _VFS[k] = content
    _VFS_DELETED.discard(k)


def _vfs_mark_deleted(path: Path) -> None:
    k = _abs(path)
    _VFS.pop(k, None)
    _VFS_DELETED.add(k)


def _vfs_get(path: Path) -> str | None:
    return _VFS.get(_abs(path))


def _file_exists(path: Path) -> bool:
    k = _abs(path)
    if k in _VFS:
        return True
    if k in _VFS_DELETED:
        return False
    return path.exists()


def _read_file(path: Path) -> str:
    v = _vfs_get(path)
    if v is not None:
        return v
    # PATCH v1.0.4: utf-8-sig — файлы с BOM читались как есть, и паттерны
    # replace/insert/regex не находили маркеры (BOM попадал в начало).
    # updater.py при сканировании уже использовал utf-8-sig — теперь
    # поведение согласовано. Запись остаётся utf-8 (без BOM).
    return path.read_text(encoding='utf-8-sig')


# ============================================================
# ЖУРНАЛ
# ============================================================
def j_load(base: Path) -> dict:
    p = base / JOURNAL
    if not p.exists():
        return {}
    # PATCH v1.0.11: битый журнал — громкая ошибка, не молчаливый {}.
    # Иначе main() начал бы применять патчи «с нуля», перезаписал файл
    # через j_save, и вся история применения (включая пути к бэкапам)
    # была бы потеряна.
    try:
        _raw = p.read_text(encoding='utf-8-sig')
        _data = json.loads(_raw)
        if not isinstance(_data, dict):
            raise ValueError('корень не объект')
        return _data
    except Exception as e:
        raise RuntimeError(
            f'Журнал {p} повреждён: {e}. '
            f'Восстановите из .patches_applied.archive-*.json '
            f'или удалите файл вручную (потеряете историю применения).'
        )


def j_save(base: Path, j: dict) -> None:
    try:
        _sorted = sorted(j.items(), key=lambda kv: (kv[1] or {}).get('applied_at') or '', reverse=True)
        for _i, (_pid, _info) in enumerate(_sorted):
            if _i >= 10 and isinstance(_info, dict) and _info.get('changes'):
                _info['changes'] = []
    except Exception as e:
        print(f'[patcher] j_save changes trim failed: {e}')
    p = base / JOURNAL
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(p)


# ============================================================
# УТИЛИТЫ
# ============================================================
def _content(op: dict) -> str:
    # PATCH v1.0.35: dict → json.dumps, а не str() с одинарными кавычками.
    # Раньше content={'a':1} → "{'a': 1}" — невалидный JSON.
    v = op.get('content', '')
    if v is None:
        return ''
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False, indent=2)
    if isinstance(v, list):
        # Обратная совместимость: массив строк — построчный join.
        # Если есть нестроковые элементы — JSON-массив.
        if all(isinstance(x, str) for x in v):
            return '\n'.join(v)
        return json.dumps(v, ensure_ascii=False, indent=2)
    return str(v)


def _field(op: dict, key: str) -> str:
    v = op.get(key, '')
    if v is None:
        return ''
    if isinstance(v, list):
        return '\n'.join(str(x) for x in v)
    return str(v)


def _stamp() -> str:
    return datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:21]


def _rel(base: Path, p: Path) -> str:
    try:
        return str(p.relative_to(base))
    except ValueError:
        return str(p)


def _preview(text: str, limit: int = 120) -> str:
    text = text.replace('\n', '\\n').replace('\r', '\\r')
    return text[:limit] + ('…' if len(text) > limit else '')


def resolve(base: Path, raw: str) -> Path | None:
    raw = str(raw or '').strip()
    if not raw:
        return None

    strict = raw.startswith('./') or raw.startswith('.\\')
    if strict:
        raw = raw[2:]

    if '*' in raw or '?' in raw:
        matches = sorted(base.glob(raw))
        return matches[0] if matches else None

    direct = (base / raw).resolve()
    if direct.exists() or _file_exists(direct):
        return direct
    if strict:
        return None

    for d in SEARCH_DIRS:
        cand = (base / d / raw).resolve()
        if cand.exists() or _file_exists(cand):
            return cand
    return None


def fuzzy_lines(text: str, needle: str, n: int = 3) -> list[tuple[int, str]]:
    first = (needle.splitlines()[0].strip() if needle else '')
    if not first:
        return []
    lines = text.splitlines()
    stripped = [l.strip() for l in lines]
    hits = difflib.get_close_matches(first, stripped, n=n, cutoff=0.55)
    out: list[tuple[int, str]] = []
    for h in hits:
        for i, l in enumerate(lines, 1):
            if l.strip() == h:
                out.append((i, l))
                break
    return out


def _not_found(ctx: dict, path: Path, text: str, needle: str, what: str) -> bool:
    ctx['log'](f'      {C.ERR}✗{C.END} {what}: не найдено в {_rel(ctx["base"], path)}')
    ctx['log'](f'        {C.DIM}нужно: {_preview(needle, 100)!r}{C.END}')
    for ln, txt in fuzzy_lines(text, needle, n=3):
        ctx['log'](f'        {C.DIM}строка {ln}: {_preview(txt, 100)!r}{C.END}')
    return False


def _backup_path(ctx: dict, src: Path) -> Path:
    try:
        rel = src.relative_to(ctx['base'])
    except ValueError:
        rel = Path(src.name)
    return ctx['backup_dir'] / rel.parent / f'{rel.name}.bak-{_stamp()}'


def _sha256_of(path: Path) -> str:
    """PATCH v1.0.8: sha256 файла для контроля целостности."""
    try:
        import hashlib as _hl
        _h = _hl.sha256()
        with path.open('rb') as _f:
            for _c in iter(lambda: _f.read(65536), b''):
                _h.update(_c)
        return _h.hexdigest()
    except Exception:
        return ''


def save_file(ctx: dict, path: Path, content: str) -> bool:
    """PATCH v1.0.7+v1.0.8: возвращает True/False. Без бэкапа операция не выполняется.
    Пишет sha_before/sha_after в changes для последующей проверки при откате."""
    existed = _file_exists(path)
    bak = None
    sha_before = ''
    if existed:
        try:
            sha_before = _sha256_of(path)
        except Exception:
            sha_before = ''
    if existed and not ctx['dry'] and not ctx['no_backup']:
        bak = _backup_path(ctx, path)
        try:
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, bak)
        except Exception as e:
            ctx['log'](f'      {C.ERR}✗ бэкап не создан: {e} — операция отменена{C.END}')
            return False
    try:
        if ctx['dry']:
            _vfs_set(path, content)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
    except Exception as e:
        ctx['log'](f'      {C.ERR}✗ запись упала: {e}{C.END}')
        if bak is not None:
            try:
                if bak.exists():
                    bak.unlink()
            except Exception:
                pass
        return False
    sha_after = '' if ctx['dry'] else _sha256_of(path)
    ctx['changes'].append({
        'path': _rel(ctx['base'], path),
        'backup': _rel(ctx['base'], bak) if bak else None,
        'created': not existed,
        'sha_before': sha_before,
        'sha_after': sha_after,
    })
    return True


# ============================================================
# ОПЕРАЦИИ
# ============================================================
def op_write(ctx, op):
    raw = op['path']
    is_glob = '*' in raw or '?' in raw
    p = resolve(ctx['base'], raw)
    if p is None and is_glob:
        ctx['log'](f'  {C.ERR}✗{C.END} write: glob без совпадений: {raw}')
        return False
    target = p or (ctx['base'] / raw).resolve()
    content = _content(op)
    if _file_exists(target):
        try:
            if _read_file(target) == content:
                ctx['log'](f'  {C.DIM}· write: {_rel(ctx["base"], target)} — без изменений{C.END}')
                return True
        except Exception:
            pass
    if not save_file(ctx, target, content):
        return False
    ctx['log'](f'  {C.OK}✓{C.END} write: {_rel(ctx["base"], target)} ({len(content)} симв.)')
    return True


def op_delete(ctx, op):
    p = resolve(ctx['base'], op['path'])
    if not p:
        if op.get('optional'):
            ctx['log'](f'  {C.DIM}· delete: {op["path"]} уже нет{C.END}')
            return True
        ctx['log'](f'  {C.ERR}✗{C.END} delete: {op["path"]} не найден')
        return False
    bak = None
    if not ctx['dry'] and not ctx['no_backup']:
        bak = _backup_path(ctx, p)
        try:
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, bak)
        except Exception as e:
            # PATCH v1.0.7: без бэкапа удаление не выполняем.
            ctx['log'](f'      {C.ERR}✗ бэкап для delete не создан: {e} — операция отменена{C.END}')
            return False
    try:
        if ctx['dry']:
            _vfs_mark_deleted(p)
        else:
            p.unlink()
    except Exception as e:
        ctx['log'](f'      {C.ERR}✗ удаление упало: {e}{C.END}')
        return False
    ctx['changes'].append({
        'path': _rel(ctx['base'], p),
        'backup': _rel(ctx['base'], bak) if bak else None,
        'created': False,
        'deleted': True,
    })
    ctx['log'](f'  {C.OK}✓{C.END} delete: {_rel(ctx["base"], p)}')
    return True


def _simple_edit(ctx, op, fn, name):
    p = resolve(ctx['base'], op['path'])
    if not p:
        if op.get('optional'):
            ctx['log'](f'  {C.DIM}· {name}: {op["path"]} не найден{C.END}')
            return True
        ctx['log'](f'  {C.ERR}✗{C.END} {name}: {op["path"]} не найден')
        return False
    txt = _read_file(p)
    add = _content(op)
    if op.get('idempotent') and add and add in txt:
        ctx['log'](f'  {C.DIM}· {name}: уже есть{C.END}')
        return True
    if not save_file(ctx, p, fn(txt, add)):
        return False
    ctx['log'](f'  {C.OK}✓{C.END} {name}: {_rel(ctx["base"], p)}')
    return True


def op_append(ctx, op):
    return _simple_edit(ctx, op, lambda t, a: t + a, 'append')


def op_prepend(ctx, op):
    return _simple_edit(ctx, op, lambda t, a: a + t, 'prepend')


def op_replace(ctx, op):
    p = resolve(ctx['base'], op['path'])
    if not p:
        if op.get('optional'):
            ctx['log'](f'  {C.DIM}· replace: {op["path"]} не найден{C.END}')
            return True
        ctx['log'](f'  {C.ERR}✗{C.END} replace: {op["path"]} не найден')
        return False
    txt = _read_file(p)
    find = _field(op, 'find')
    if not find:
        if op.get('optional'):
            ctx['log'](f'  {C.DIM}· replace: пустой find, пропуск{C.END}')
            return True
        ctx['log'](f'  {C.ERR}✗{C.END} replace: пустой find — операция отклонена')
        return False
    if find not in txt:
        if op.get('optional'):
            ctx['log'](f'  {C.DIM}· replace: не найдено, пропуск{C.END}')
            return True
        return _not_found(ctx, p, txt, find, 'replace')
    try:
        count = int(op.get('count', 0))
    except (TypeError, ValueError):
        count = 0
    add = _content(op)
    if count > 0:
        new = txt.replace(find, add, count)
        n = min(count, txt.count(find))
    else:
        new = txt.replace(find, add)
        n = txt.count(find)
    if not save_file(ctx, p, new):
        return False
    ctx['log'](f'  {C.OK}✓{C.END} replace: {_rel(ctx["base"], p)} ({n}×)')
    return True


def op_regex(ctx, op):
    p = resolve(ctx['base'], op['path'])
    if not p:
        if op.get('optional'):
            ctx['log'](f'  {C.DIM}· regex: {op["path"]} не найден{C.END}')
            return True
        ctx['log'](f'  {C.ERR}✗{C.END} regex: {op["path"]} не найден')
        return False
    txt = _read_file(p)
    pattern = _field(op, 'pattern')
    if not pattern:
        if op.get('optional'):
            ctx['log'](f'  {C.DIM}· regex: пустой pattern, пропуск{C.END}')
            return True
        ctx['log'](f'  {C.ERR}✗{C.END} regex: пустой pattern — операция отклонена')
        return False
    try:
        rx = re.compile(pattern)
    except re.error as e:
        ctx['log'](f'  {C.ERR}✗{C.END} regex: плохой паттерн: {e}')
        return False
    if not rx.search(txt):
        if op.get('optional'):
            ctx['log'](f'  {C.DIM}· regex: нет совпадений, пропуск{C.END}')
            return True
        return _not_found(ctx, p, txt, pattern, 'regex')
    try:
        count = int(op.get('count', 0))
    except (TypeError, ValueError):
        count = 0
    new, n = rx.subn(_content(op), txt, count=count)
    if not save_file(ctx, p, new):
        return False
    ctx['log'](f'  {C.OK}✓{C.END} regex: {_rel(ctx["base"], p)} ({n}×)')
    return True


def op_insert(ctx, op):
    p = resolve(ctx['base'], op['path'])
    if not p:
        if op.get('optional'):
            ctx['log'](f'  {C.DIM}· insert: {op["path"]} не найден{C.END}')
            return True
        ctx['log'](f'  {C.ERR}✗{C.END} insert: {op["path"]} не найден')
        return False
    txt = _read_file(p)
    marker = _field(op, 'marker')
    idx = txt.find(marker)
    if idx < 0:
        if op.get('optional'):
            ctx['log'](f'  {C.DIM}· insert: маркер не найден, пропуск{C.END}')
            return True
        return _not_found(ctx, p, txt, marker, 'insert')
    add = _content(op)
    if op.get('idempotent') and add and add in txt:
        ctx['log'](f'  {C.DIM}· insert: уже вставлено{C.END}')
        return True
    pos = (op.get('position') or 'after').strip().lower()
    if pos == 'before':
        new = txt[:idx] + add + txt[idx:]
    else:
        end = idx + len(marker)
        new = txt[:end] + add + txt[end:]
    if not save_file(ctx, p, new):
        return False
    ctx['log'](f'  {C.OK}✓{C.END} insert({pos}): {_rel(ctx["base"], p)}')
    return True


def op_replace_block(ctx, op):
    p = resolve(ctx['base'], op['path'])
    if not p:
        if op.get('optional'):
            ctx['log'](f'  {C.DIM}· replace_block: {op["path"]} не найден{C.END}')
            return True
        ctx['log'](f'  {C.ERR}✗{C.END} replace_block: {op["path"]} не найден')
        return False
    txt = _read_file(p)
    sm = _field(op, 'start_marker')
    em = _field(op, 'end_marker')
    si = txt.find(sm)
    if si < 0:
        return _not_found(ctx, p, txt, sm, 'replace_block:start_marker')
    ei = txt.find(em, si + len(sm))
    if ei < 0:
        return _not_found(ctx, p, txt, em, 'replace_block:end_marker')
    keep_start = bool(op.get('keep_start', False))
    keep_end = bool(op.get('keep_end', False))
    from_pos = si + len(sm) if keep_start else si
    to_pos = ei if keep_end else ei + len(em)
    new = txt[:from_pos] + _content(op) + txt[to_pos:]
    if not save_file(ctx, p, new):
        return False
    ctx['log'](f'  {C.OK}✓{C.END} replace_block: {_rel(ctx["base"], p)}')
    return True


def op_rename(ctx, op):
    src = resolve(ctx['base'], op['src'])
    if not src:
        if op.get('optional'):
            ctx['log'](f'  {C.DIM}· rename: {op["src"]} не найден{C.END}')
            return True
        ctx['log'](f'  {C.ERR}✗{C.END} rename: {op["src"]} не найден')
        return False
    dst = (ctx['base'] / op['dst']).resolve()
    if _file_exists(dst) and not op.get('force'):
        ctx['log'](f'  {C.ERR}✗{C.END} rename: {op["dst"]} уже существует (нужен force:true)')
        return False
    bak = None
    if not ctx['dry'] and not ctx['no_backup']:
        bak = _backup_path(ctx, src)
        try:
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, bak)
        except Exception as e:
            # PATCH v1.0.7: без бэкапа rename не выполняем.
            ctx['log'](f'      {C.ERR}✗ бэкап для rename не создан: {e} — операция отменена{C.END}')
            return False
    try:
        if ctx['dry']:
            try:
                body = _read_file(src)
                _vfs_mark_deleted(src)
                _vfs_set(dst, body)
            except Exception as e:
                ctx['log'](f'      {C.WARN}⚠ dry-rename: {e}{C.END}')
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
    except Exception as e:
        ctx['log'](f'      {C.ERR}✗ rename упал: {e}{C.END}')
        return False
    ctx['changes'].append({
        'path': _rel(ctx['base'], src),
        'backup': _rel(ctx['base'], bak) if bak else None,
        'created': False,
    })
    ctx['changes'].append({'path': _rel(ctx['base'], dst), 'created': True})
    ctx['log'](f'  {C.OK}✓{C.END} rename: {op["src"]} → {op["dst"]}')
    return True


OPS = {
    'write':         op_write,
    'delete':        op_delete,
    'append':        op_append,
    'prepend':       op_prepend,
    'replace':       op_replace,
    'regex':         op_regex,
    'insert':        op_insert,
    'replace_block': op_replace_block,
    'rename':        op_rename,
}

OPS_HELP = {
    'write':         'создать/перезаписать файл                          (path, content)',
    'delete':        'удалить файл                                      (path, optional)',
    'append':        'добавить в конец файла                            (path, content, idempotent)',
    'prepend':       'добавить в начало файла                           (path, content, idempotent)',
    'replace':       'заменить подстроку                                (path, find, content, count=0|N, optional)',
    'regex':         'заменить по регулярке                             (path, pattern, content, count=0|N, optional)',
    'insert':        'вставить до/после маркера                         (path, marker, position=after|before, content)',
    'replace_block': 'заменить блок между маркерами                     (path, start_marker, end_marker, content, keep_start, keep_end)',
    'rename':        'переименовать/переместить                         (src, dst, force)',
}


# ============================================================
# ПРИМЕНЕНИЕ
# ============================================================
def apply_patch(patch: dict, base: Path, *, dry: bool = False,
                no_backup: bool = False,
                backup_dir: Path | None = None) -> tuple[bool, list]:
    if backup_dir is None:
        backup_dir = base / BACKUP_DIR_NAME
    ctx = {
        'base': base,
        'dry': dry,
        'no_backup': no_backup,
        'backup_dir': backup_dir,
        'log': print,
        'changes': [],
    }
    ops = patch.get('operations') or []
    if not isinstance(ops, list) or not ops:
        print('  (нет операций)')
        return True, []
    ok_all = True
    for i, op in enumerate(ops, 1):
        t = op.get('type', '?')
        target = op.get('path') or op.get('src') or ''
        prefix = '[DRY] ' if dry else ''
        print(f'  {prefix}[{i}/{len(ops)}] {t}: {target}')
        handler = OPS.get(t)
        if not handler:
            print(f'      {C.ERR}✗{C.END} неизвестный тип: {t}')
            ok_all = False
            continue
        try:
            if not handler(ctx, op):
                ok_all = False
        except Exception as e:
            print(f'      {C.ERR}✗{C.END} ошибка: {e}')
            ok_all = False
    # Auto-rollback при частичном применении:
    # если какая-то операция упала, восстанавливаем уже изменённые файлы
    # из только что созданных бэкапов и удаляем вновь созданные,
    # чтобы не осталось «полу-применённого» состояния без записи в журнал.
    if not ok_all and not dry and ctx['changes']:
        print(f'  {C.WARN}⚠ Откат изменений патча (частичное применение)...{C.END}')
        for ch in reversed(ctx['changes']):
            p = base / ch['path']
            if ch.get('created'):
                try:
                    if p.exists():
                        p.unlink()
                        print(f'    🗑  удалён {ch["path"]}')
                except Exception as e:
                    print(f'    {C.WARN}⚠ не удалось удалить {ch["path"]}: {e}{C.END}')
            elif ch.get('backup'):
                bak = base / ch['backup']
                try:
                    if bak.exists():
                        shutil.copy2(bak, p)
                        print(f'    ↺  восстановлен {ch["path"]}')
                except Exception as e:
                    print(f'    {C.WARN}⚠ не удалось восстановить {ch["path"]}: {e}{C.END}')
        ctx['changes'] = []

    return ok_all, ctx['changes']


# ============================================================
# СОРТИРОВКА ПО ВЕРСИИ + REQUIRES
# ============================================================
def _ver_tuple(s):
    try:
        parts = str(s or '').strip().split('.')
        out = []
        for p in parts[:4]:
            out.append(int(p))
        while len(out) < 3:
            out.append(0)
        return tuple(out)
    except Exception:
        return (0, 0, 0)


def _read_patch_meta(path: Path) -> dict:
    pid = ''
    tv = (0, 0, 0)
    req = []
    ok = False
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            pid = str(data.get('id') or '').strip()
            tv = _ver_tuple(data.get('target_version') or '')
            req = list(data.get('requires') or [])
            ok = True
    except Exception:
        pass
    if not ok:
        m = re.match(r'^v?(\d+(?:\.\d+){1,3})', path.stem)
        if m:
            pid = pid or ('v' + m.group(1))
            tv = _ver_tuple(m.group(1))
        else:
            pid = pid or path.stem
    return {'id': pid, 'version': tv, 'requires': req, 'ok': ok}


def _sort_patch_files(files: list[Path]) -> list[Path]:
    metas = {f: _read_patch_meta(f) for f in files}
    ordered: list[Path] = []
    placed_ids: set[str] = set()
    remaining = list(files)

    guard = 0
    while remaining and guard < len(files) * 2 + 5:
        guard += 1
        ready = [f for f in remaining
                 if all(r in placed_ids for r in metas[f]['requires'])]
        if not ready:
            ready = remaining[:]
        ready.sort(key=lambda f: (metas[f]['version'], metas[f]['id']))
        pick = ready[0]
        ordered.append(pick)
        placed_ids.add(metas[pick]['id'])
        remaining.remove(pick)

    if remaining:
        ordered.extend(sorted(remaining,
                              key=lambda f: (metas[f]['version'], metas[f]['id'])))
    return ordered


# ============================================================
# МИГРАЦИЯ СТАРЫХ БЭКАПОВ
# ============================================================
def migrate_old_backups(base: Path, journal: dict) -> int:
    moved = 0
    new_root = base / BACKUP_DIR_NAME
    prefix_posix = BACKUP_DIR_NAME + '/'
    prefix_win = BACKUP_DIR_NAME + '\\'

    for pid, info in journal.items():
        for ch in (info.get('changes') or []):
            b = ch.get('backup')
            if not b:
                continue
            if b.startswith(prefix_posix) or b.startswith(prefix_win):
                continue
            old = base / b
            if not old.exists():
                continue
            rel_path = Path(ch.get('path') or old.name)
            new = new_root / rel_path.parent / old.name
            new.parent.mkdir(parents=True, exist_ok=True)
            if new.exists():
                continue
            try:
                shutil.move(str(old), str(new))
                ch['backup'] = _rel(base, new)
                moved += 1
            except Exception as e:
                print(f'{C.WARN}⚠ не перенесён {old}: {e}{C.END}')
    if moved:
        j_save(base, journal)
    return moved


# ============================================================
# ОТКАТ
# ============================================================
def rollback(pid: str, base: Path, journal: dict) -> bool:
    info = journal.get(pid)
    if not info:
        print(f'{C.ERR}Патч «{pid}» не найден в журнале{C.END}')
        return False
    changes = info.get('changes') or []
    if not changes:
        print('Нет данных для отката')
        return False
    print(f'Откат {pid}: {len(changes)} изменений')
    # PATCH v1.0.7: возвращаем False при неудаче.
    # PATCH v1.0.8: проверяем, что файл в состоянии после патча (sha_after).
    failed = []
    modified_after = []
    for ch in reversed(changes):
        p = base / ch['path']
        if ch.get('created'):
            try:
                if p.exists():
                    p.unlink()
                    print(f'  🗑  удалён {ch["path"]}')
            except Exception as e:
                print(f'  {C.ERR}✗ не удалён {ch["path"]}: {e}{C.END}')
                failed.append(ch['path'])
        elif ch.get('backup'):
            bak = base / ch['backup']
            if not bak.exists():
                print(f'  {C.ERR}✗ нет бэкапа: {ch["backup"]}{C.END}')
                print(f'    {C.DIM}файл {ch["path"]} остаётся в текущем состоянии{C.END}')
                failed.append(ch['path'])
                continue
            expected = (ch.get('sha_after') or '').strip()
            if expected and p.exists():
                cur = _sha256_of(p)
                if cur and cur != expected:
                    modified_after.append(ch['path'])
            try:
                shutil.copy2(bak, p)
                print(f'  ↺  восстановлен {ch["path"]}')
            except Exception as e:
                print(f'  {C.ERR}✗ не восстановлен {ch["path"]}: {e}{C.END}')
                failed.append(ch['path'])
        else:
            print(f'  {C.ERR}✗ бэкап не записан при применении: {ch["path"]}{C.END}')
            failed.append(ch['path'])
    if modified_after:
        print(f'  {C.WARN}⚠ Файлы правились после патча — правки затёрты откатом: '
              f'{", ".join(modified_after)}{C.END}')
    if failed:
        print(f'  {C.ERR}✗ Не восстановлены файлы ({len(failed)}): {", ".join(failed)}{C.END}')
        print(f'  {C.WARN}⚠ Патч ОСТАЁТСЯ в журнале. Состояние системы — ЧАСТИЧНЫЙ откат.{C.END}')
        print(f'  {C.WARN}⚠ Восстановите файлы вручную или из резервной копии,{C.END}')
        print(f'  {C.WARN}  затем удалите запись «{pid}» из .patches_applied.json.{C.END}')
        return False
    return True


# ============================================================
# MAIN
# ============================================================
def _rollback_session(pids, base, journal):
    """PATCH v1.0.7: откат списка патчей в обратном порядке.
    Возвращает True, если все откатились без ошибок."""
    ok = True
    for _pid in reversed(list(pids)):
        try:
            if rollback(_pid, base, journal):
                print(f'  ↺ откачен {_pid}')
                journal.pop(_pid, None)
            else:
                print(f'  {C.ERR}✗ не удалось откатить {_pid}{C.END}')
                ok = False
        except Exception as e:
            print(f'  {C.ERR}✗ откат {_pid}: {e}{C.END}')
            ok = False
    j_save(base, journal)
    return ok


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description='patcher.py v4 — патчер с chained dry-run',
    )
    ap.add_argument('patch', nargs='?', help='.json патч или папка с *.json')
    ap.add_argument('--dry', action='store_true', help='dry-run: изменения в памяти, без записи на диск')
    ap.add_argument('--force', action='store_true', help='переприменить уже применённые')
    ap.add_argument('--no-backup', action='store_true', help='не создавать .bak')
    ap.add_argument('--base', default=None, help='корень проекта (по умолчанию рядом с patcher.py)')
    ap.add_argument('--backup-dir', default=None,
                    help='куда складывать бэкапы (по умолчанию <base>/patch_backups)')
    ap.add_argument('--only', default=None, help='применить только патч с этим id')
    ap.add_argument('--applied', action='store_true', help='список применённых патчей')
    ap.add_argument('--rollback', metavar='ID', help='откат применённого патча по id')
    ap.add_argument('--migrate-backups', action='store_true',
                    help='разово перенести старые *.bak-* в patch_backups/')
    ap.add_argument('--list-ops', action='store_true', help='справка по операциям')
    args = ap.parse_args()

    if args.list_ops:
        print(f'{C.BOLD}Поддерживаемые операции:{C.END}')
        for name, text in OPS_HELP.items():
            print(f'  {C.INFO}{name:<15}{C.END} {text}')
        return 0

    base = Path(args.base).resolve() if args.base else BASE_DIR
    if not base.exists():
        print(f'{C.ERR}Корень проекта не найден: {base}{C.END}')
        return 1
    # PATCH v1.0.11: j_load теперь бросает RuntimeError при повреждённом
    # журнале — иначе main() тихо начал бы с {} и перезаписал файл.
    try:
        journal = j_load(base)
    except RuntimeError as _e:
        print(f'{C.ERR}{_e}{C.END}')
        return 1

    if args.migrate_backups:
        n = migrate_old_backups(base, journal)
        print(f'{C.OK}Перенесено бэкапов: {n}{C.END}')
        print(f'{C.INFO}Папка: {base / BACKUP_DIR_NAME}{C.END}')
        return 0

    if args.applied:
        if not journal:
            print('Нет применённых патчей.')
            return 0
        print(f'Применено: {len(journal)}')
        for pid in sorted(journal):
            info = journal[pid]
            print(f'  {C.BOLD}•{C.END} {pid}   '
                  f'{info.get("applied_at", "?")}   {info.get("description", "")}')
        return 0

    if args.rollback:
        if rollback(args.rollback, base, journal):
            journal.pop(args.rollback, None)
            j_save(base, journal)
            print(f'{C.OK}Готово.{C.END}')
            return 0
        return 1

    if not args.patch:
        ap.print_help()
        return 1

    pp = Path(args.patch)
    if pp.is_dir():
        files = _sort_patch_files(list(pp.glob('*.json')))
    elif pp.exists():
        files = [pp]
    else:
        print(f'{C.ERR}Не найдено: {pp}{C.END}')
        return 1
    if not files:
        print(f'{C.ERR}В {pp} нет *.json{C.END}')
        return 1

    backup_dir = (Path(args.backup_dir).resolve()
                  if args.backup_dir else (base / BACKUP_DIR_NAME))

    # PATCH v4: dry-run ведёт overlay — сбрасываем его перед прогоном.
    if args.dry:
        _vfs_reset()

    ok_n = fail_n = skip_n = 0

    for f in files:
        print(f'\n{C.BOLD}=== {f.name} ==={C.END}')
        try:
            patch = json.loads(f.read_text(encoding='utf-8'))
        except Exception as e:
            print(f'{C.ERR}Ошибка чтения: {e}{C.END}')
            fail_n += 1
            continue

        pid = patch.get('id') or f.stem
        desc = patch.get('description', '')

        if args.only and pid != args.only:
            skip_n += 1
            continue

        print(f'{C.INFO}ID:{C.END} {pid}')
        if desc:
            print(f'{C.INFO}Описание:{C.END} {desc}')

        missing = [r for r in (patch.get('requires') or []) if r not in journal]
        if missing and not args.dry:
            print(f'{C.ERR}Требуются патчи: {", ".join(missing)}{C.END}')
            fail_n += 1
            continue
        if missing and args.dry:
            # В dry-режиме считаем, что предыдущие патчи этой же цепочки
            # «применяются в той же сессии» — не блокируем из-за них.
            print(f'  {C.DIM}(dry) requires в этой же цепочке: {", ".join(missing)}{C.END}')

        if pid in journal and not args.force and not args.dry:
            print(f'  {C.WARN}· уже применён {journal[pid].get("applied_at", "?")}. '
                  f'Пропуск (--force, чтобы применить заново).{C.END}')
            skip_n += 1
            continue

        ok, changes = apply_patch(
            patch, base,
            dry=args.dry, no_backup=args.no_backup,
            backup_dir=backup_dir,
        )

        if ok and not args.dry:
            journal[pid] = {
                'applied_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'description': desc,
                'target_version': str(patch.get('target_version') or '').strip(),
                'operations_count': len(patch.get('operations') or []),
                'changes': changes,
            }
            j_save(base, journal)
            print(f'  {C.OK}✓ применён. Изменений: {len(changes)}{C.END}')
            ok_n += 1
        elif ok:
            print(f'  {C.INFO}(dry) изменений было бы: {len(changes)}{C.END}')
            ok_n += 1
        else:
            print(f'  {C.ERR}✗ не применён из-за ошибок{C.END}')
            fail_n += 1
            # PATCH v1.0.7 + v1.0.10: fail-fast в обоих режимах.
            # PATCH v1.0.10: в dry-run тоже прерываем — иначе _VFS накопит
            # частичное состояние упавшего патча, и следующий dry-run-патч
            # проверится на «грязной» картине (false positive/negative).
            _mode = '(dry) ' if args.dry else ''
            print(f'{C.WARN}{_mode}Цепочка прервана на патче «{pid}». '
                  f'Все последующие не проверены — исправьте и перезапустите.{C.END}')
            break

    print()
    tail = f'  {C.WARN}[DRY]{C.END}' if args.dry else ''
    print(f'Итог: {C.OK}ok {ok_n}{C.END}  fail {fail_n}  skip {skip_n}{tail}')
    return 0 if fail_n == 0 else 1


if __name__ == '__main__':
    sys.exit(main())

