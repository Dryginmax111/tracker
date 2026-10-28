#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор патчей v1.1.4–v1.1.8. Читает реальные файлы core/, находит точные
фрагменты (с учётом CRLF) и пишет JSON в patches/. Падает, если якорь не найден."""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).parent
CORE = ROOT / 'core'
OUT = ROOT / 'patches'
OUT.mkdir(exist_ok=True)

def read(rel):
    return (CORE / rel).read_text(encoding='utf-8')

def find_span(text, start_sub, end_sub, name):
    i = text.find(start_sub)
    if i < 0:
        raise SystemExit(f'[gen] ЯКОРЬ НЕ НАЙДЕН: {name} :: {start_sub[:60]!r}')
    j = text.find(end_sub, i + len(start_sub))
    if j < 0:
        raise SystemExit(f'[gen] КОНЦОВИК НЕ НАЙДЕН: {name} :: {end_sub[:60]!r}')
    return i, j + len(end_sub)

def write_patch(pid, desc, target, requires, ops):
    p = {'id': pid, 'description': desc, 'target_version': target,
         'requires': requires, 'ops': ops}
    f = OUT / f'{pid}.json'
    f.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[gen] OK -> {f.name} ({len(ops)} ops)')

def crlf(s):
    return s.replace('\n', '\r\n')

import os as _os
NL = '\r\n' if _os.environ.get('PATCH_NL', 'crlf') == 'crlf' else '\n'

# ============================================================
# v1.1.4 — админка: блоки на вкладке «База данных» + светлая тема
# ============================================================
sh = read('tamplates/settings.html')
i0 = sh.find('<div class="settings-panel" id="sp-db">')
assert i0 >= 0, 'sp-db not found'
i1 = sh.find('<div class="settings-panel" id="sp-plugins">')
db_block = sh[i0:i1]

groups = list(re.finditer(r'<div class="form-group"[^>]*>', db_block))
assert len(groups) == 10, f'expected 10 form-groups in sp-db, got {len(groups)}'
titles = ['📁 Расположение файла', '🌐 Сетевые обновления', '💾 Резервные копии',
          '🧹 Очистка базы данных', '📊 Расчёт статистики', '📅 График работы',
          '🔒 Безопасность выгрузок', '🧩 Плагины']

new_db = db_block
for gi in range(len(groups) - 1, -1, -1):
    g_start = groups[gi].start()
    g_end = groups[gi + 1].start() if gi + 1 < len(groups) else len(db_block)
    # конец последней группы — перед </div>\r\n\r\n    {# PATCH
    grp = new_db[g_start:g_end]
    strip_tail = grp.rstrip()
    if gi == len(groups) - 1:
        tail = grp[len(strip_tail):]
        grp = strip_tail + '\r\n'
    t = titles[gi] if gi < 8 else titles[-1]
    wrapped = ('<div class="db-block">\r\n'
               '<div class="db-block-head"><span class="dbh-icon">' + t.split(' ', 1)[0] + '</span>'
               '<span>' + t.split(' ', 1)[1] + '</span></div>\r\n'
               + re.sub(r' style="margin-top:(18|10)px;"', '', grp)
               + '\r\n</div>')
    new_db = new_db[:g_start] + wrapped + new_db[g_end:]

new_db = new_db.replace('<div class="settings-toolbar"><div class="dict-section-title">Расположение базы данных</div></div>',
                        '<div class="settings-toolbar"><div class="dict-section-title">💾 Расположение базы данных</div>'
                        '<button type="button" class="theme-toggle-btn" id="trkThemeToggle"><span id="trkThemeIcon">☀️</span> '
                        '<span id="trkThemeLabel">Светлая</span></button></div>', 1)
new_db = new_db.replace('<div class="settings-panel" id="sp-db">',
                        '<div class="settings-panel" id="sp-db">\r\n    <div class="db-grid">', 1)
new_db += '<!-- db-grid close -->\r\n'
# закрыть db-grid перед завершением панели: добавим </div> перед финальным </div> блока
m = re.search(r'(</div>\s*)$', new_db)
new_db = new_db[:m.start()] + '</div>\r\n    ' + new_db[m.start():]

CSS_14 = '''

/* ==== v1.1.4: вкладки админки как плагины (light/dark через plugin_theme.js) ==== */
.settings-container{max-width:1200px;margin:0 auto;padding:16px}
body.trk-theme-light .settings-container{background:transparent;color:#1a1d21}
body.trk-theme-light .settings-header,body.trk-theme-light .settings-tabs,
body.trk-theme-light .settings-panel,body.trk-theme-light .settings-user,
body.trk-theme-light .db-path-row input,body.trk-theme-light select,body.trk-theme-light textarea{
  background:#ffffff!important;border-color:rgba(0,0,0,.14)!important;color:#1a1d21!important;
  box-shadow:0 2px 10px rgba(0,0,0,.06)!important}
body.trk-theme-light .settings-tab{color:#5b6470;background:transparent!important}
body.trk-theme-light .settings-tab.active{background:#e9fff8!important;color:#00695c!important}
body.trk-theme-light .dict-section-title,body.trk-theme-light .su-name{color:#1a1d21!important}
body.trk-theme-light .su-sub,body.trk-theme-light .db-path-note,body.trk-theme-light .settings-hint{color:#5b6470!important}
body.trk-theme-light .dict-add-btn{filter:brightness(1.05)}
body.trk-theme-light .user-chip{background:#f2f4f7!important;color:#1a1d21!important}
body.trk-theme-light .pwd-form input,body.trk-theme-light .hol-add-row input{
  background:#fff!important;color:#1a1d21!important;border-color:rgba(0,0,0,.18)!important}

/* ==== v1.1.4: вкладка «База данных» — карточные блоки ==== */
.db-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px;align-items:start}
.db-block{background:var(--trk-card-bg,#151a21);border:1px solid var(--trk-card-border,#232a33);
  border-radius:14px;padding:14px 16px;display:flex;flex-direction:column;gap:4px;
  box-shadow:0 4px 14px rgba(0,0,0,.18);transition:border-color .15s}
.db-block:hover{border-color:var(--trk-accent,#00897b)}
.db-block .form-group{margin:0;padding:0}
.db-block-head{display:flex;align-items:center;gap:8px;font-size:.8rem;font-weight:800;
  letter-spacing:.4px;text-transform:uppercase;color:var(--trk-accent,#00897b);
  padding-bottom:8px;margin-bottom:8px;border-bottom:1px solid var(--trk-card-border,#232a33)}
.db-block-head .dbh-icon{font-size:1rem}
.theme-toggle-btn{margin-left:auto;padding:7px 14px;border-radius:20px;cursor:pointer;
  border:1px solid var(--trk-card-border,#232a33);background:transparent;color:var(--trk-text,#e6e6e6);
  font-family:inherit;font-size:.78rem;font-weight:700;display:inline-flex;gap:6px;align-items:center}
.theme-toggle-btn:hover{border-color:var(--trk-accent,#00897b);color:var(--trk-accent,#00897b)}
@media(max-width:760px){.db-grid{grid-template-columns:1fr}}
'''

JS_14 = '''
/* ==== v1.1.4: переключатель темы в админке (light/dark) ==== */
(function(){
'use strict';
function apply(theme){
    document.body.classList.remove('trk-theme-dark','trk-theme-light');
    document.body.classList.add('trk-theme-' + theme);
    document.documentElement.setAttribute('data-trk-theme', theme);
    try{ localStorage.setItem('reestr_tracker_theme', theme); }catch(e){}
    var icon=document.getElementById('trkThemeIcon'), lbl=document.getElementById('trkThemeLabel');
    if(icon) icon.textContent = theme==='dark' ? '☀️' : '🌙';
    if(lbl) lbl.textContent = theme==='dark' ? 'Светлая' : 'Тёмная';
}
var saved='dark'; try{ saved=localStorage.getItem('reestr_tracker_theme')||'dark'; }catch(e){}
apply(saved);
document.addEventListener('click', function(e){
    if(e.target && e.target.closest && e.target.closest('#trkThemeToggle')) apply(document.body.classList.contains('trk-theme-light')?'dark':'light');
});
})();
'''

write_patch('v1.1.4-admin-db-blocks',
    'Админка: вкладка «База данных» разбита на карточные блоки (сетка), добавлена светлая тема (кнопка ☀️/🌙)',
    '1.1.4', [], [
    {'op': 'replace', 'path': 'client_version.json',
     'find': '"version": "1.1.2"', 'content': '"version": "1.1.4"'},
    {'op': 'replace', 'path': 'tamplates/settings.html',
     'find': db_block, 'content': new_db},
    {'op': 'append', 'path': 'static/app.css', 'content': CSS_14, 'idempotent': True},
    {'op': 'append', 'path': 'static/settings.js', 'content': JS_14, 'idempotent': True},
])

# ============================================================
# v1.1.5 — компактные праздники в админке
# ============================================================
ss = read('static/settings.js')
i, j = find_span(ss, 'function renderHolidays(){', 'wrap.innerHTML = html;', 'renderHolidays')
old_render = ss[i:j]
new_render = old_render.replace(
    "html += '<div class=\"settings-user\" data-date=\"' + esc(k) + '\">'",
    "html += '<div class=\"hol-chip\" data-date=\"' + esc(k) + '\" title=\"' + esc(k) + '\">'")
new_render = new_render.replace(
    "+ '<div class=\"su-main\"><div class=\"su-name\">🎉 ' + esc(state.holidays[k]) + '</div>'",
    "+ '🎉 <span class=\"hc-name\">' + esc(state.holidays[k]) + '</span>'")
new_render = new_render.replace(
    "+ '<div class=\"su-sub\">' + esc(k) + '</div></div>'",
    "+ '<span class=\"hc-date\">' + esc(k.slice(8,10) + '.' + k.slice(5,7)) + '</span>'")
assert new_render != old_render
CSS_15 = '''
/* ==== v1.1.5: компактные чипы праздников ==== */
#holidaysList{display:flex;flex-wrap:wrap;gap:6px}
.hol-chip{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:16px;
  font-size:.78rem;background:var(--trk-input-bg,#1a2027);border:1px solid var(--trk-card-border,#232a33);
  color:var(--trk-text,#e6e6e6);white-space:nowrap}
.hol-chip .hc-date{color:var(--trk-meta,#8a94a0);font-weight:700;font-size:.72rem}
.hol-chip .dict-action-btn{padding:1px 6px;font-size:.72rem;border-radius:10px}
body.trk-theme-light .hol-chip{background:#fff!important;color:#1a1d21!important}
'''
write_patch('v1.1.5-admin-holidays-compact',
    'Админка: вкладка «Праздники» — компактный вид записей (чипы вместо полноразмерных карточек)',
    '1.1.5', ['v1.1.4-admin-db-blocks'], [
    {'op': 'replace', 'path': 'client_version.json',
     'find': '"version": "1.1.4"', 'content': '"version": "1.1.5"'},
    {'op': 'replace', 'path': 'static/settings.js', 'find': old_render, 'content': new_render},
    {'op': 'append', 'path': 'static/app.css', 'content': CSS_15, 'idempotent': True},
])

# ============================================================
# v1.1.6 — смена пароля в «Мой профиль»
# ============================================================
mp = read('plugins/my_profile.py')
i, j = find_span(mp, "    @app.route('/api/plugins/my_profile/vacation/add', methods=['POST'])",
                 "    def _mp_vac_add():", 'vac_add anchor')
PWD_ROUTE = '''    @app.route('/api/plugins/my_profile/password', methods=['POST'])
    def _mp_password():
        # v1.1.6: обычный пользователь может сменить СВОЙ пароль
        u = _auth_user()
        if not u: return jsonify({'success': False, 'error': 'auth'}), 401
        body = request.get_json() or {}
        old = str(body.get('old_password') or '')
        new = str(body.get('new_password') or '')
        rep = str(body.get('new_password2') or '')
        if len(new) < 6:
            return jsonify({'success': False, 'error': 'Новый пароль: минимум 6 символов'}), 400
        if new != rep:
            return jsonify({'success': False, 'error': 'Пароли не совпадают'}), 400
        try:
            from auth import verify_password, hash_password
            if not verify_password(u['password_hash'], old):
                return jsonify({'success': False, 'error': 'Неверный текущий пароль'}), 400
            db.user_update(u['id'], u['role'], u.get('display_name', ''),
                           u.get('employee_id', ''), True, pwd_hash=hash_password(new))
        except Exception as ex:
            return jsonify({'success': False, 'error': 'Ошибка: ' + str(ex)[:80]}), 500
        return jsonify({'success': True})

'''
TAB_BTN = '''    <button class="tab" data-tab="password">🔑 Пароль</button>
'''
i2, j2 = find_span(mp, '<div class="panel" id="panel-import">', '<div class="panel" id="panel-import">', 'panel-import tag')
PWD_PANEL = '''  <div class="panel" id="panel-password">
    <h2 style="margin:0 0 12px 0;font-size:1rem">🔑 Смена пароля</h2>
    <div style="display:flex;flex-direction:column;gap:10px;max-width:380px">
      <input id="pw_old" type="password" placeholder="Текущий пароль" autocomplete="current-password"
        style="padding:9px 12px;border-radius:8px;border:1px solid var(--pg-card-border);background:var(--pg-input-bg);color:var(--pg-text);font-family:inherit">
      <input id="pw_new" type="password" placeholder="Новый пароль (мин. 6 символов)" autocomplete="new-password"
        style="padding:9px 12px;border-radius:8px;border:1px solid var(--pg-card-border);background:var(--pg-input-bg);color:var(--pg-text);font-family:inherit">
      <input id="pw_new2" type="password" placeholder="Повторите новый пароль" autocomplete="new-password"
        style="padding:9px 12px;border-radius:8px;border:1px solid var(--pg-card-border);background:var(--pg-input-bg);color:var(--pg-text);font-family:inherit">
      <button id="pwSave" style="padding:9px 16px;border:none;border-radius:8px;background:var(--pg-accent);color:#fff;font-weight:700;cursor:pointer;font-family:inherit">💾 Сменить пароль</button>
      <div id="pwMsg" style="font-size:.8rem;color:var(--pg-meta)"></div>
    </div>
  </div>

'''
i3, j3 = find_span(mp, "loadData();", "loadData();", 'tail')
tail_area = mp[j2:]
m = re.search(r"</script>", tail_area)
assert m, 'no closing script in page html'
PWD_JS = '''
// v1.1.6: смена пароля
(function(){
    var btn=document.getElementById('pwSave'); if(!btn) return;
    btn.addEventListener('click', function(){
        var msg=document.getElementById('pwMsg');
        var payload={old_password:document.getElementById('pw_old').value,
                     new_password:document.getElementById('pw_new').value,
                     new_password2:document.getElementById('pw_new2').value};
        fetch('/api/plugins/my_profile/password',{method:'POST',
            headers:{'Content-Type':'application/json','X-CSRF-Token':window.REESTR_CSRF||''},
            body:JSON.stringify(payload)})
        .then(function(r){return r.json();}).then(function(d){
            if(d.success){msg.style.color='#2e7d32';msg.textContent='✅ Пароль изменён';
                ['pw_old','pw_new','pw_new2'].forEach(function(id){document.getElementById(id).value='';});}
            else{msg.style.color='#c62828';msg.textContent='❌ '+(d.error||'Ошибка');}
        }).catch(function(e){msg.style.color='#c62828';msg.textContent='❌ '+e;});
    });
})();
'''
new_mp = (mp[:j] + PWD_ROUTE + mp[j:])
new_mp = new_mp.replace('    <button class="tab" data-tab="import" id="tabImport" style="display:none;">📥 Импорт из Excel</button>',
                        TAB_BTN + '    <button class="tab" data-tab="import" id="tabImport" style="display:none;">📥 Импорт из Excel</button>', 1)
new_mp = new_mp.replace('<div class="panel" id="panel-import">', PWD_PANEL + '<div class="panel" id="panel-import">', 1)
idx_script_end = new_mp.find('</script>', new_mp.find(PWD_PANEL))
new_mp = new_mp[:idx_script_end] + PWD_JS + new_mp[idx_script_end:]
write_patch('v1.1.6-profile-change-password',
    '«Мой профиль»: обычному пользователю можно сменить свой пароль (вкладка 🔑 Пароль + API)',
    '1.1.6', ['v1.1.4-admin-db-blocks'], [
    {'op': 'replace', 'path': 'client_version.json',
     'find': '"version": "1.1.5"', 'content': '"version": "1.1.6"'},
    {'op': 'replace', 'path': 'plugins/my_profile.py', 'find': mp, 'content': new_mp},
])

# ============================================================
# v1.1.7 — справочники: datalist должностей, ✏️ отпуск, убрать Праздники
# ============================================================
tj = read('static/tracker.js')

# op A: кнопка ✏️ в vacList
iB, jB = find_span(tj,
    "+ '</div><button class=\"dict-action-btn danger\" data-vac-id=\"' + _vid + '\" data-idx=\"' + i + '\" type=\"button\">🗑</button></div>';",
    "+ '</div><button class=\"dict-action-btn danger\" data-vac-id=\"' + _vid + '\" data-idx=\"' + i + '\" type=\"button\">🗑</button></div>';",
    'vac delete btn')
OP_B_OLD = tj[iB:jB]
OP_B_NEW = ("+ '</div>'\n"
            "            + (canEditVac ? '<button class=\"dict-action-btn\" data-vac-edit=\"1\" data-vac-id=\"' + _vid + '\" type=\"button\" title=\"Изменить период\">✏️</button>' : '')\n"
            "            + (canEditVac ? '<button class=\"dict-action-btn danger\" data-vac-id=\"' + _vid + '\" data-idx=\"' + i + '\" type=\"button\">🗑</button>' : '')\n"
            "            + '</div>';")
# добавить canEditVac и обработчик edit
iCan, jCan = find_span(tj, 'function renderVacations(emp) {', "    var vac = (emp && emp.vacations) || [];", 'renderVacations head')
HEAD_OLD = tj[iCan:jCan]
HEAD_NEW = ("function renderVacations(emp) {\n"
            "    var list = $('vacList'); if (!list) return;\n"
            "    // v1.1.7: редактирование отпусков прямо из карточки сотрудника\n"
            "    var canEditVac = !!(window.REESTR_PERMS && window.REESTR_PERMS['action.employee.vacation.edit']);\n"
            "    var _editId = null;\n"
            "    var vac = (emp && emp.vacations) || [];")
# хвост renderVacations: навешиваем обработчик ✏️ перед closing of forEach listeners block
iTail, jTail = find_span(tj,
    "            }).catch(function(err) { if (err && (err.message || '').indexOf('cancelled') !== -1) return; notify('❌ ' + (err.message || 'Ошибка'), 'error'); });\n        });\n    });\n}",
    "    });\n}",
    'renderVacations tail')
TAIL_OLD = tj[iTail:jTail]
TAIL_NEW = TAIL_OLD[:-1] + """
    list.querySelectorAll('[data-vac-edit]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var vid = parseInt(this.getAttribute('data-vac-id'), 10);
            var v = vac.filter(function(x){ return x.id === vid; })[0];
            if (!v) return;
            var g = function(id, val) { var el = $(id); if (el) el.value = val || ''; };
            g('vac_type', v.type || 'vacation'); g('vac_from', v.from || ''); g('vac_to', v.to || ''); g('vac_comment', v.comment || '');
            _editId = vid;
            var ab = $('vacAddBtn'); if (ab) ab.textContent = '💾 Сохранить изменения';
            notify('✏️ Правьте даты и нажмите «Сохранить изменения»', 'info');
        });
    });
}"""
# vacAddBtn: режим update
iAdd, jAdd = find_span(tj, "on('vacAddBtn', 'click', function() {",
                       "apiJson('/api/tracker/employee/vacation/add', {", 'vacAddBtn')
ADD_OLD_TAIL = tj[jAdd:tj.find("    }).then(function(d) {", jAdd)]
ADD_FULL_OLD = tj[iAdd: tj.find("    }).then(function(d) {", jAdd)]
_add_anchor = ("apiJson('/api/tracker/employee/vacation/add', {" + NL + "        method: 'POST', headers: {'Content-Type': 'application/json'}," + NL + "        body: JSON.stringify({ employee_id: _vacDraftEmpId, from: from, to: to, type: vtype, comment: comment })")
assert _add_anchor in ADD_FULL_OLD, 'add anchor not found'
ADD_FULL_NEW = ADD_FULL_OLD.replace(_add_anchor,
    "var _url = (_editId != null) ? '/api/tracker/employee/vacation/update' : '/api/tracker/employee/vacation/add';\n"
    "    var _pl = { employee_id: _vacDraftEmpId, from: from, to: to, type: vtype, comment: comment };\n"
    "    if (_editId != null) _pl.id = _editId;\n"
    "    apiJson(_url, {\n        method: 'POST', headers: {'Content-Type': 'application/json'},\n        body: JSON.stringify(_pl)")
_g_anchor = "        var g = function(id) { var el = $(id); if (el) el.value = ''; };" + NL + "        g('vac_from'); g('vac_to'); g('vac_comment');"
assert _g_anchor in ADD_FULL_NEW, 'g anchor not found'
ADD_FULL_NEW = ADD_FULL_NEW.replace(_g_anchor, _g_anchor + NL + "        _editId = null; var _ab = $('vacAddBtn'); if (_ab) _ab.textContent = '📾 Сохранить; кнопка обрачно не нужна';")
ADD_FULL_NEW = ADD_FULL_NEW.replace("_editId = null; var _ab = $('vacAddBtn'); if (_ab) _ab.textContent = '📾 Сохранить; кнопка обрачно не нужна';", "_editId = null; var _ab = $('vacAddBtn'); if (_ab) _ab.textContent = '\u2795 \u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c';".replace('\u2795','➕').replace('\u0414','Д'))

th = read('tamplates/tracker.html')
iH, jH = find_span(th, '<div class="dict-section">\r\n                    <div class="dict-section-head">\r\n                        <span class="dict-section-title">🎉 Праздники</span>',
                   '</div>\r\n                </div>\r\n            </div>\r\n        </div>', 'holidays block')
HOL_OLD = th[iH:jH]
HOL_NEW = '{# v1.1.7: Праздники убраны из справочников — ведутся в Админке #}\r\n                </div>\r\n            </div>\r\n        </div>'

AP = read('app.py')
iV, jV = find_span(AP, "    @app.route('/api/tracker/employee/vacation/delete', methods=['POST'])",
                   "    def api_vacation_delete():", 'vac delete route')
VAC_UPDATE = '''    @app.route('/api/tracker/employee/vacation/update', methods=['POST'])
    @login_required
    @permission_required('action.employee.vacation.edit')
    def api_vacation_update():
        # v1.1.7: редактирование периода отсутствия из карточки сотрудника
        body = request.get_json() or {}
        emp_id = str(body.get('employee_id', '')).strip()
        try:
            vid = int(body.get('id'))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Некорректный id'}), 400
        row = db.query_one('SELECT id FROM employee_vacations WHERE id=? AND employee_id=?', (vid, emp_id))
        if not row:
            return jsonify({'success': False, 'error': 'Период не найден'}), 404
        vtype = str(body.get('type', 'vacation')).strip()
        if vtype not in ABSENCE_TYPES:
            vtype = 'vacation'
        dfrom = str(body.get('from', '')).strip()
        dto = str(body.get('to', '')).strip()
        comment = str(body.get('comment', '')).strip()[:200]
        if not _valid_date(dfrom) or not _valid_date(dto):
            return jsonify({'success': False, 'error': 'Некорректные даты'}), 400
        if dfrom > dto:
            dfrom, dto = dto, dfrom
        others = db.query('SELECT date_from, date_to FROM employee_vacations WHERE employee_id=? AND id!=?', (emp_id, vid))
        for v in others:
            if not (v['date_to'] < dfrom or v['date_from'] > dto):
                return jsonify({'success': False, 'error': 'Пересекается с другим периодом'}), 409
        db.exec('UPDATE employee_vacations SET date_from=?, date_to=?, vtype=?, comment=? WHERE id=? AND employee_id=?',
                (dfrom, dto, vtype, comment, vid, emp_id))
        _audit(db, current_user(db), 'update', 'vacation', emp_id,
               {'vacation_id': vid, 'from': dfrom, 'to': dto, 'type': vtype})
        return jsonify({'success': True})

'''
write_patch('v1.1.7-dicts-fixes',
    'Справочники: живой выпадающий список должностей (+ ручной ввод), редактирование отпусков из карточки (✏️ + API update), Праздники убраны с вкладки',
    '1.1.7', ['v1.1.5-admin-holidays-compact'], [
    {'op': 'replace', 'path': 'client_version.json',
     'find': '"version": "1.1.6"', 'content': '"version": "1.1.7"'},
    {'op': 'replace', 'path': 'static/tracker.js', 'find': HEAD_OLD, 'content': HEAD_NEW},
    {'op': 'replace', 'path': 'static/tracker.js', 'find': OP_B_OLD, 'content': OP_B_NEW},
    {'op': 'replace', 'path': 'static/tracker.js', 'find': TAIL_OLD, 'content': TAIL_NEW},
    {'op': 'replace', 'path': 'static/tracker.js', 'find': ADD_FULL_OLD, 'content': ADD_FULL_NEW},
    {'op': 'regex', 'path': 'static/tracker.js',
     'pattern': r"(if \(dl\) dl\.innerHTML = roles\.map)",
     'content': r"window.__trkFillRoleDatalist = fillRoleDatalist; \1"},
    {'op': 'regex', 'path': 'static/tracker.js',
     'pattern': r"return loadState\(\);\r?\n(\s+)\}\)\.then\(function\(\) \{\r?\n\s+var emp2 = state\.employees\.find\(function\(x\) \{ return x\.id === _vacDraftEmpId; \}\);\r?\n\s+renderVacations\(emp2\);",
     'content': "return loadState();\n\\1}).then(function() {\n\\1    var emp2 = state.employees.find(function(x) { return x.id === _vacDraftEmpId; });\n\\1    renderVacations(emp2);\n\\1    try { if (window.__trkFillRoleDatalist) window.__trkFillRoleDatalist(); } catch(e) {}"},
    {'op': 'replace', 'path': 'app.py', 'find': AP[iV:jV], 'content': VAC_UPDATE + AP[iV:jV]},
    {'op': 'replace', 'path': 'tamplates/tracker.html', 'find': HOL_OLD, 'content': HOL_NEW},
])

# ============================================================
# v1.1.8 — спойлеры задач + плагин «Отчёт за день»
# ============================================================
iS, jS = find_span(tj, "while (grp.firstChild) body.appendChild(grp.firstChild);",
                  "while (grp.firstChild) body.appendChild(grp.firstChild);", 'spoiler move')
SP_OLD = tj[iS:jS]
SP_NEW = ("var _lbl = grp.querySelector(':scope > label');\n"
          "            if (_lbl) _lbl.parentNode.removeChild(_lbl); // v1.1.8: без дублирующей подписи под спойлером\n            " + SP_OLD)

import pathlib as _pl
DR_PY = _pl.Path('plugins_daily_report_src.py').read_text(encoding='utf-8')

_page = None

def _page_html():
    global _page
    if _page is not None:
        return _page
    _page = r'''<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>🌅 Отчёт за день</title>
<script src="/static/plugin_theme.js"></script>
<style>
''' + _CSS_VARS + '''
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;margin:0;padding:18px;
  font-size:14px;background:var(--pg-bg);color:var(--pg-text);min-height:100vh}
.w{max-width:1280px;margin:0 auto;display:flex;flex-direction:column;gap:14px}
.head{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:14px 18px;background:var(--pg-card-bg);
  border:1px solid var(--pg-card-border);border-radius:14px}
.head h1{margin:0;font-size:1.15rem;font-weight:800;color:var(--pg-accent)}
.back{color:var(--pg-desc);text-decoration:none;padding:6px 14px;border:1px solid var(--pg-card-border);
  border-radius:20px;font-size:.85rem}.back:hover{background:var(--pg-accent-bg);color:var(--pg-accent)}
.nav{display:flex;gap:8px;align-items:center;margin-left:auto;flex-wrap:wrap}
.nav button{padding:7px 12px;border-radius:8px;border:1px solid var(--pg-card-border);background:transparent;
  color:var(--pg-text);cursor:pointer;font-family:inherit;font-weight:700}
.nav button:hover{border-color:var(--pg-accent);color:var(--pg-accent)}
.nav input[type=date]{padding:7px 10px;border-radius:8px;border:1px solid var(--pg-card-border);
  background:var(--pg-input-bg);color:var(--pg-text);font-family:inherit}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.kpi{background:var(--pg-card-bg);border:1px solid var(--pg-card-border);border-radius:14px;padding:14px 16px;
  display:flex;flex-direction:column;gap:4px;position:relative;overflow:hidden}
.kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--kc,var(--pg-accent))}
.kpi .v{font-size:1.5rem;font-weight:800;color:var(--kc,var(--pg-accent))}
.kpi .l{font-size:.72rem;text-transform:uppercase;letter-spacing:.5px;color:var(--pg-meta)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
.card{background:var(--pg-card-bg);border:1px solid var(--pg-card-border);border-radius:14px;padding:14px 16px}
.card h2{margin:0 0 10px 0;font-size:.85rem;text-transform:uppercase;letter-spacing:.5px;color:var(--pg-accent)}
table{width:100%;border-collapse:collapse;font-size:.83rem}
th{text-align:left;padding:7px 8px;font-size:.68rem;text-transform:uppercase;color:var(--pg-meta);
  border-bottom:1px solid var(--pg-card-border)}
td{padding:7px 8px;border-bottom:1px solid rgba(128,128,128,.12)}
.bar{height:6px;border-radius:3px;background:var(--pg-input-bg);overflow:hidden;min-width:70px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--pg-accent),var(--pg-accent-2))}
.pill{display:inline-block;padding:2px 9px;border-radius:12px;font-size:.72rem;font-weight:700;
  background:var(--pg-accent-bg);color:var(--pg-accent)}
.pill.warn{background:rgba(245,215,110,.14);color:var(--pg-yellow)}
.pill.danger{background:rgba(236,112,99,.14);color:var(--pg-red)}
.pill.ok{background:rgba(88,214,141,.14);color:var(--pg-green)}
.feed-item{display:flex;gap:10px;padding:9px 4px;border-bottom:1px solid rgba(128,128,128,.12);align-items:flex-start}
.feed-item:last-child{border-bottom:none}
.fi-av{width:30px;height:30px;border-radius:50%;flex:none;display:flex;align-items:center;justify-content:center;
  color:#fff;font-weight:800;font-size:.7rem;background:var(--fc,var(--pg-accent))}
.fi-body{flex:1;min-width:0}
.fi-top{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.fi-name{font-weight:700;font-size:.85rem}
.fi-task{color:var(--pg-blue);font-size:.8rem}
.fi-text{color:var(--pg-desc);font-size:.82rem;margin-top:3px;white-space:pre-wrap;word-break:break-word}
.absent{display:flex;flex-wrap:wrap;gap:6px}
.empty{color:var(--pg-meta);padding:14px;text-align:center}
</style></head><body><div class="w">
<div class="head"><h1>🌅 Отчёт за день</h1>
  <a class="back" href="/">← Трекер</a>
  <div class="nav"><button id="prevD">←</button><input type="date" id="pickD"><button id="nextD">→</button>
  <button id="todayBtn">Сегодня</button></div></div>
<div class="kpis" id="kpis"></div>
<div class="grid2">
  <div class="card"><h2>🏢 По отделам</h2><div id="byDept"></div></div>
  <div class="card"><h2>👤 Сотрудники</h2><div style="overflow:auto"><table id="empTbl"><thead><tr>
    <th>Сотрудник</th><th>Отдел</th><th style="text-align:right">Часы</th><th>Загрузка</th><th>Отметки</th>
    <th style="text-align:right">Закрыто</th></tr></thead><tbody></tbody></table></div></div>
</div>
<div class="card"><h2>🏖 Не работают сегодня</h2><div class="absent" id="absent"></div></div>
<div class="card"><h2>🗒 Лента отметок</h2><div id="feed"></div></div>
</div>
<script>
var CSRF = "__CSRF_TOKEN__";
var cur = new Date().toISOString().slice(0,10);
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function shift(d,n){var x=new Date(d+'T00:00:00');x.setDate(x.getDate()+n);return x.toISOString().slice(0,10);}
function load(){
  document.getElementById('pickD').value=cur;
  fetch('/api/plugins/daily_report/data?date='+cur,{headers:{'X-CSRF-Token':CSRF}})
  .then(function(r){if(r.status===401||r.status===403){location.href='/login';throw 0;}return r.json();})
  .then(render).catch(function(){});
}
function avColor(n){var h=0;s=String(n||'?');for(var i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))%360;return 'hsl('+h+',45%,40%)';}
function render(d){
  var k=d.kpi||{};
  var items=[['🕐 Часов отмечено',(k.hours||0)+' ч','var(--pg-accent)'],
             ['✍️ Отметок',k.entries||0,'var(--pg-blue)'],
             ['👥 На работе',(k.present||0)+'/'+(k.expected||0),'var(--pg-green)'],
             ['✅ Закрыто сегодня',k.closed||0,'var(--pg-green)'],
             ['⚠️ Просрочено',k.overdue||0,'var(--pg-red)'],
             ['🏖 Отсутствуют',k.absent||0,'var(--pg-yellow)']];
  document.getElementById('kpis').innerHTML=items.map(function(x){
    return '<div class="kpi" style="--kc:'+x[2]+'"><div class="v">'+x[1]+'</div><div class="l">'+x[0]+'</div></div>';}).join('');
  var dep=d.departments||[];
  document.getElementById('byDept').innerHTML=dep.length?('<table><thead><tr><th>Отдел</th><th>Люди</th>'+
    '<th style="text-align:right">Часы</th><th>Активность</th></tr></thead><tbody>'+dep.map(function(x){
    return '<tr><td>'+esc(x.name)+'</td><td>'+x.people+'</td><td style="text-align:right"><b>'+x.hours+' ч</b></td>'+
    '<td><div class="bar"><i style="width:'+Math.min(100,x.pct||0)+'%"></i></div></td></tr>';}).join('')+'</tbody></table>')
    :'<div class="empty">нет данных</div>';
  var emps=d.employees||[],mx=Math.max.apply(null,[1].concat(emps.map(function(x){return x.hours||0;})));
  document.querySelector('#empTbl tbody').innerHTML=emps.length?emps.map(function(x){
    var st=x.absent_type?('<span class="pill warn">'+esc(x.absent_label)+'</span>'):
      ((x.hours>=8)?'<span class="pill ok">норма</span>':(x.hours>0?'<span class="pill">недобор</span>':'<span class="pill danger">пусто</span>'));
    return '<tr><td><b>'+esc(x.name)+'</b></td><td style="color:var(--pg-meta)">'+esc(x.dept)+'</td>'+
    '<td style="text-align:right"><b>'+x.hours+'</b> ч</td>'+
    '<td><div class="bar"><i style="width:'+Math.round((x.hours||0)/mx*100)+'%"></i></div> '+st+'</td>'+
    '<td>'+x.entries+'</td><td style="text-align:right">'+x.closed+'</td></tr>';}).join(''):'<tr><td colspan="6" class="empty">нет данных</td></tr>';
  var ab=d.absent||[];
  document.getElementById('absent').innerHTML=ab.length?ab.map(function(x){
    return '<span class="pill warn">🏖 '+esc(x.name)+' · '+esc(x.label)+(x.period?(' · '+x.period):'')+'</span>';}).join(''):'<div class="empty">Все на работе 🎯</div>';
  var fd=d.feed||[];
  document.getElementById('feed').innerHTML=fd.length?fd.map(function(x){
    var links=(x.links||[]).map(function(l){return '<a href="'+esc(l)+'" target="_blank" style="color:var(--pg-blue)">🔗</a>';}).join(' ');
    return '<div class="feed-item"><div class="fi-av" style="--fc:'+avColor(x.name)+'">'+esc((x.name||'?')[0])+'</div>'+
    '<div class="fi-body"><div class="fi-top"><span class="fi-name">'+esc(x.name)+'</span>'+
    (x.task?('<span class="fi-task">→ '+esc(x.task)+'</span>'):'')+
    '<span class="pill'+(x.hours>=8?' ok':(x.hours>0?'':' warn'))+'">'+x.hours+' ч</span>'+
    (x.status?('<span class="pill">'+esc(x.status)+'</span>'):'')+'</div>'+
    '<div class="fi-text">'+esc(x.text)+(links?(' '+links):'')+'</div></div></div>';}).join(''):'<div class="empty">За этот день отметок нет</div>';
}
document.getElementById('prevD').onclick=function(){cur=shift(cur,-1);load();};
document.getElementById('nextD').onclick=function(){cur=shift(cur,1);load();};
document.getElementById('todayBtn').onclick=function(){cur=new Date().toISOString().slice(0,10);load();};
document.getElementById('pickD').onchange=function(){cur=this.value;load();};
load();
</script></body></html>'''
    return _page


_JS = r'''
(function(){
'use strict';
function register(){
    if (typeof window.__trkRegisterPlugin !== 'function') { setTimeout(register, 200); return; }
    window.__trkRegisterPlugin({
        id: 'daily_report',
        icon: '🌅',
        name: 'Отчёт за день',
        url: '/plugins/daily_report/',
        perm: 'plugin.capacity.use'
    });
}
register();
})();
'''


def _status_label(t):
    return {'open': 'в работе', 'progress': 'в работе', 'done': 'закрыта',
            'review': 'на проверке', 'blocked': 'заблокирована'}.get(str(t or ''), str(t or ''))


def _build(db, day):
    st = db.load_all()
    employees = st.get('employees') or []
    tasks = st.get('tasks') or []
    log = st.get('log') or {}
    deps = {d['id']: d.get('name', '') for d in (st.get('departments') or [])}
    entries = log.get(day) or []
    by_emp = {}
    closed_ids = set()
    for e in entries:
        eid = str(e.get('employee_id') or '')
        a = by_emp.setdefault(eid, {'hours': 0.0, 'entries': 0, 'closed': 0})
        a['hours'] += float(e.get('hours') or 0)
        a['entries'] += 1
        if str(e.get('status') or '').lower() in ('done', 'closed', 'закрыт', 'закрыта'):
            a['closed'] += 1
            tid = str(e.get('task_id') or '')
            if tid:
                closed_ids.add(tid)
    norm = 8.0
    sched = (db.get_setting('work_schedule') or 'legacy')
    wd = datetime.strptime(day, '%Y-%m-%d').weekday()
    if sched == 'extended':
        norm = {0: 8.25, 1: 8.25, 2: 8.25, 3: 8.25, 4: 7.75}.get(wd, 0.0)
    else:
        norm = 8.0 if wd < 5 else 0.0
    hol = (st.get('holidays') or {}).get(day)
    if hol:
        norm = 0.0
    absent = []
    emp_rows = []
    dept_agg = {}
    for emp in employees:
        if emp.get('fired'):
            continue
        eid = str(emp['id'])
        dname = deps.get(str(emp.get('department_id') or ''), '—')
        v_now = None
        for v in (emp.get('vacations') or []):
            if (v.get('from') or '9999') <= day <= (v.get('to') or '0000'):
                v_now = v
                break
        agg = by_emp.get(eid, {'hours': 0.0, 'entries': 0, 'closed': 0})
        atype = (v_now or {}).get('type') or ''
        alabel = ''
        if atype:
            alabel = {'vacation': 'отпуск', 'sick': 'больничный', 'business_trip': 'командировка',
                      'remote': 'удалёнка', 'dayoff': 'выходной', 'other': 'отсутствие'}.get(atype, atype)
            if alabel not in ('командировка', 'удалёнка'):
                absent.append({'name': emp.get('name', ''), 'label': alabel,
                               'period': (v_now.get('from', '') + ' — ' + v_now.get('to', '')) if v_now else ''})
        if not hol and (not atype or atype in ('business_trip', 'remote')):
            expected = 1
        elif atype in ('business_trip', 'remote'):
            expected = 1
        else:
            expected = 0
        emp_rows.append({'name': emp.get('name', ''), 'dept': dname,
                         'hours': round(agg['hours'], 2), 'entries': agg['entries'],
                         'closed': agg['closed'], 'expected': expected,
                         'absent_type': atype, 'absent_label': alabel})
        da = dept_agg.setdefault(dname, {'people': 0, 'hours': 0.0})
        da['people'] += 1
        da['hours'] += agg['hours']
    mx_dept = max([1.0] + [v['hours'] for v in dept_agg.values()])
    dlist = [{'name': k, 'people': v['people'], 'hours': round(v['hours'], 1),
              'pct': round(v['hours'] / mx_dept * 100)} for k, v in sorted(dept_agg.items())]
    task_by_id = {str(t.get('id')): t for t in tasks}
    feed = []
    for e in entries:
        emp = next((x for x in employees if str(x['id']) == str(e.get('employee_id') or '')), None)
        ed = e.get('extra_data') or {}
        if isinstance(ed, str):
            try:
                import json as _j
                ed = _j.loads(ed)
            except Exception:
                ed = {}
        links = []
        for l in (ed.get('links_multi') or []):
            u = l.get('url') if isinstance(l, dict) else l
            if u:
                links.append(u)
        feed.append({'name': (emp or {}).get('name', '?'),
                     'task': (task_by_id.get(str(e.get('task_id') or ''), {}) or {}).get('title', ''),
                     'hours': round(float(e.get('hours') or 0), 2),
                     'status': _status_label(e.get('status')),
                     'text': e.get('text', ''), 'links': links[:3]})
    overdue = sum(1 for t in tasks
                  if str(t.get('status') or '').lower() not in ('done', 'closed', 'закрыт', 'закрыта')
                  and t.get('deadline') and t['deadline'] < day)
    present = sum(1 for r in emp_rows if r['expected'])
    kpi = {'hours': round(sum(r['hours'] for r in emp_rows), 1), 'entries': len(entries),
           'present': present, 'expected': present + sum(1 for r in emp_rows if not r['expected'] and not r['absent_type']),
           'closed': len(closed_ids), 'overdue': overdue, 'absent': len(absent)}
    emp_rows.sort(key=lambda r: (-r['hours'], r['name']))
    return {'date': day, 'holiday': hol or '', 'kpi': kpi, 'departments': dlist,
            'employees': emp_rows, 'absent': absent, 'feed': feed[:120]}


def register(app, db, hooks):
    print(f'[daily_report] v{__version__} · {__description__}')

    def _u():
        try:
            from auth import current_user, user_has
            u = current_user(db)
            if not u:
                return None
            if u.get('role') != 'admin' and not user_has(db, u, 'plugin.capacity.use'):
                return None
            return u
        except Exception:
            return None

    @app.route('/plugins-assets/daily_report.js', methods=['GET'])
    def _dr_js():
        return app.response_class(_JS, mimetype='application/javascript')

    @app.route('/plugins/daily_report/', methods=['GET'])
    def _dr_page():
        if not _u():
            return redirect('/login')
        tok = ''
        try:
            from auth import ensure_csrf
            tok = ensure_csrf() or ''
        except Exception:
            pass
        return Response(_page_html().replace('__CSRF_TOKEN__', tok), mimetype='text/html')

    @app.route('/api/plugins/daily_report/data', methods=['GET'])
    def _dr_data():
        if not _u():
            return jsonify({'success': False, 'error': 'auth'}), 401
        raw = (request.args.get('date') or '').strip()
        try:
            datetime.strptime(raw, '%Y-%m-%d')
        except ValueError:
            raw = date.today().isoformat()
        try:
            return jsonify({'success': True, **_build(db, raw)})
        except Exception as ex:
            return jsonify({'success': False, 'error': str(ex)[:200]}), 500
'''

iP, jP = find_span(th, '<script src="/plugins-assets/reminders.js"></script>',
                   '<script src="/plugins-assets/reminders.js"></script>', 'reminders script')
write_patch('v1.1.8-daily-report-and-spoilers',
    'Задачи: убраны дубли подписей «Ссылки/Приказы» в спойлерах; Статистика: новый плагин «🌅 Отчёт за день»',
    '1.1.8', ['v1.1.7-dicts-fixes'], [
    {'op': 'replace', 'path': 'client_version.json',
     'find': '"version": "1.1.7"', 'content': '"version": "1.1.8"'},
    {'op': 'replace', 'path': 'static/tracker.js', 'find': SP_OLD, 'content': SP_NEW},
    {'op': 'write', 'path': 'plugins/daily_report.py', 'content': DR_PY},
    {'op': 'insert', 'path': 'tamplates/tracker.html',
     'marker': '<script src="/plugins-assets/reminders.js"></script>',
     'position': 'after',
     'content': '\r\n<script src="/plugins-assets/daily_report.js"></script>',
     'idempotent': True},
])

print('[gen] все патчи сгенерированы')
