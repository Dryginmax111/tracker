"""plugins/task_heatmap.py — Тепловая карта задач (v3 - Filters)."""
__version__ = '1.3'
__description__ = 'Матрица Задачи × Дни с мультифильтрами'

from datetime import date, datetime, timedelta
from flask import request, jsonify, Response, redirect


def _page_html():
    return r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Тепловая карта задач</title>
<script src="/static/plugin_theme.js"></script>
<script src="/static/plugin_mask.js"></script>
<style>
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;margin:0;padding:16px;font-size:14px;background:var(--pg-bg);color:var(--pg-text);min-height:100vh}
.w{max-width:1800px;margin:0 auto;display:flex;flex-direction:column;gap:14px}

/* Шапка */
.head{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:14px 18px;background:var(--pg-card-bg);border:1px solid var(--pg-card-border);border-radius:14px}
.head h1{margin:0;font-size:1.2rem;font-weight:800;color:var(--pg-accent)}
.back{color:var(--pg-desc);text-decoration:none;padding:6px 14px;border:1px solid var(--pg-card-border);border-radius:20px;font-size:.85rem}
.back:hover{background:var(--pg-accent-bg);color:var(--pg-accent)}

/* Тулбар */
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:12px 16px;background:var(--pg-card-bg);border:1px solid var(--pg-card-border);border-radius:12px}
.toolbar select,.toolbar input{padding:6px 10px;border-radius:8px;border:1px solid var(--pg-input-border);background:var(--pg-input-bg);color:var(--pg-text);font-family:inherit;font-size:.82rem}
.toolbar button.prim{padding:6px 18px;border-radius:8px;border:none;background:linear-gradient(135deg,var(--pg-accent),var(--pg-accent-2));color:#0a0a0a;font-weight:700;font-family:inherit;font-size:.82rem;cursor:pointer}

.presets{display:flex;gap:2px;background:var(--pg-inner-bg);padding:2px;border-radius:8px}
.presets button{padding:4px 12px;border-radius:6px;background:transparent;border:none;color:var(--pg-desc);font-size:.78rem;cursor:pointer;font-weight:600}
.presets button.active{background:var(--pg-accent-bg);color:var(--pg-accent)}

/* Мультиселекты */
.multi-wrap{position:relative;display:inline-block}
.multi-btn{padding:6px 12px;border-radius:8px;border:1px solid var(--pg-input-border);background:var(--pg-input-bg);color:var(--pg-text);font-size:.82rem;cursor:pointer;display:flex;align-items:center;gap:6px;min-width:140px;justify-content:space-between}
.multi-btn:hover{border-color:var(--pg-accent)}
.multi-btn .count{background:var(--pg-accent);color:#000;padding:1px 6px;border-radius:10px;font-size:.7rem;font-weight:800}
.multi-drop{position:absolute;top:100%;left:0;margin-top:4px;background:var(--pg-card-bg);border:1px solid var(--pg-card-border);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.3);z-index:100;min-width:220px;max-height:300px;overflow-y:auto;display:none;padding:6px}
.multi-drop.active{display:block}
.multi-item{display:flex;align-items:center;gap:8px;padding:6px 10px;border-radius:6px;cursor:pointer;font-size:.82rem;user-select:none}
.multi-item:hover{background:var(--pg-inner-bg)}
.multi-item input[type="checkbox"]{accent-color:var(--pg-accent);margin:0}
.multi-clear{width:100%;padding:8px;background:transparent;border:none;border-top:1px solid var(--pg-border-soft);color:var(--pg-err);font-size:.78rem;cursor:pointer;font-family:inherit}

/* Таблица */
.hm-wrap{overflow:auto;max-height:75vh;border:1px solid var(--pg-card-border);border-radius:12px;background:var(--pg-card-bg);padding:16px}
.hm-table{border-collapse:collapse;font-size:.8rem;width:100%}

.hm-table th{background:transparent;color:var(--pg-meta);font-weight:700;font-size:.7rem;padding:8px 4px;text-align:center;position:sticky;top:0;z-index:3;min-width:36px;border-bottom:1px solid var(--pg-border-soft)}
.hm-table th.weekend{color:rgba(128,128,128,.5)}
.hm-table th.today{color:var(--pg-accent);font-size:.8rem}

.hm-table th.task-col{text-align:left;min-width:260px;padding-left:0;position:sticky;left:0;z-index:5;background:var(--pg-card-bg);font-size:.75rem;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--pg-border-soft)}
.hm-table td.task-cell{text-align:left;position:sticky;left:0;z-index:2;background:var(--pg-card-bg);padding:6px 16px 6px 0;min-width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--pg-text);font-weight:700;height:40px;border-bottom:1px solid var(--pg-border-soft)}

.hm-table td.day-cell{padding:4px;height:40px;text-align:center;vertical-align:middle;border-bottom:1px solid var(--pg-border-soft)}
.hm-pill{display:inline-flex;align-items:center;justify-content:center;width:100%;min-width:32px;height:28px;border-radius:6px;font-size:.72rem;font-weight:800;transition:transform .15s,box-shadow .15s;cursor:pointer}

.hm-pill.none{background:rgba(128,128,128,.04)}
.hm-pill.is-weekend.none{background:rgba(128,128,128,.1)}

.hm-pill.st-planned{background:rgba(149,165,166,.25);color:#546e7a}
.hm-pill.st-in_progress{background:rgba(52,152,219,.2);color:#1565c0}
.hm-pill.st-done{background:rgba(46,204,113,.2);color:#1b5e20}
.hm-pill.st-blocked{background:rgba(231,76,60,.2);color:#b71c1c}

.hm-pill.h-1{background:rgba(52,152,219,.2)}
.hm-pill.h-2{background:rgba(52,152,219,.35)}
.hm-pill.h-3{background:rgba(52,152,219,.55);color:#fff}
.hm-pill.h-4{background:rgba(52,152,219,.8);color:#fff}

.hm-pill.done-1{background:rgba(46,204,113,.2)}
.hm-pill.done-2{background:rgba(46,204,113,.4)}
.hm-pill.done-3{background:rgba(46,204,113,.6);color:#fff}
.hm-pill.done-4{background:rgba(46,204,113,.85);color:#fff}

.hm-pill:hover{transform:scale(1.1);box-shadow:0 4px 12px rgba(0,0,0,.15);z-index:10}

/* Тултип */
.hm-tooltip{position:fixed;z-index:9999;background:var(--pg-card-bg);border:1px solid var(--pg-card-border);border-radius:8px;padding:10px 14px;font-size:.78rem;box-shadow:0 8px 24px rgba(0,0,0,.2);pointer-events:none;display:none;max-width:280px;line-height:1.5;color:var(--pg-text)}
.hm-tooltip .tt-title{font-weight:800;color:var(--pg-accent);margin-bottom:4px;font-size:.9rem}
.hm-tooltip .tt-row{display:flex;justify-content:space-between;margin-top:4px;gap:10px;border-top:1px solid var(--pg-border-soft);padding-top:4px}
.hm-tooltip .tt-row b{color:var(--pg-text)}

.empty{text-align:center;padding:40px;color:var(--pg-meta);font-style:italic}

@media(max-width:800px){
    .hm-table th.task-col, .hm-table td.task-cell{min-width:180px}
    .hm-wrap{padding:8px}
}
</style>
</head>
<body>
<div class="w">

    <div class="head">
        <a class="back" href="/">← К трекеру</a>
        <h1>🔥 Тепловая карта задач</h1>
    </div>

    <div class="toolbar">
        <div class="presets" id="periodPresets">
            <button data-p="week">Неделя</button>
            <button data-p="month" class="active">Месяц</button>
            <button data-p="quarter">Квартал</button>
            <button data-p="year">Год</button>
        </div>
        
        <div style="display:flex;gap:4px;align-items:center;">
            <input type="date" id="fFrom" style="width:130px">
            <input type="date" id="fTo" style="width:130px">
            <button class="prim" id="fApply">Применить</button>
        </div>

        <!-- Мультиселекты -->
        <div class="multi-wrap" id="deptWrap">
            <div class="multi-btn" id="deptBtn">Отделы <span class="count" id="deptCnt" style="display:none;">0</span> ▾</div>
            <div class="multi-drop" id="deptDrop"></div>
        </div>

        <div class="multi-wrap" id="teamWrap">
            <div class="multi-btn" id="teamBtn">Команды <span class="count" id="teamCnt" style="display:none;">0</span> ▾</div>
            <div class="multi-drop" id="teamDrop"></div>
        </div>

        <div class="multi-wrap" id="tagWrap">
            <div class="multi-btn" id="tagBtn">Теги <span class="count" id="tagCnt" style="display:none;">0</span> ▾</div>
            <div class="multi-drop" id="tagDrop"></div>
        </div>

        <select id="fTask" style="margin-left:auto;"><option value="">Все задачи</option></select>
    </div>

    <div class="hm-wrap" id="hmWrap">
        <div class="empty">Загрузка...</div>
    </div>
</div>

<div class="hm-tooltip" id="hmTooltip"></div>

<script>
(function(){
'use strict';

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function fmtD(iso){if(!iso)return'';var p=iso.split('-');return p[2]+'.'+p[1];}

var state = { preset: 'month', from: '', to: '', depts: [], teams: [], tags: [] };
var _TT_DATA = {};

// === Рендер мультиселектов ===
function renderMulti(elId, dropId, cntId, items, selected, onChange) {
    var drop = document.getElementById(dropId);
    var cnt = document.getElementById(cntId);
    var html = '';
    items.forEach(function(item){
        var isSel = selected.indexOf(item.id) !== -1;
        html += '<label class="multi-item"><input type="checkbox" value="' + item.id + '"' + (isSel ? ' checked' : '') + '> ' + esc(item.name) + '</label>';
    });
    if (selected.length) html += '<button class="multi-clear">Очистить</button>';
    drop.innerHTML = html;
    
    if (selected.length) { cnt.style.display = ''; cnt.textContent = selected.length; }
    else { cnt.style.display = 'none'; }

    drop.querySelectorAll('input').forEach(function(cb){
        cb.addEventListener('change', function(){
            var val = this.value;
            var idx = selected.indexOf(val);
            if (this.checked && idx === -1) selected.push(val);
            else if (!this.checked && idx !== -1) selected.splice(idx, 1);
            onChange();
        });
    });
    var clr = drop.querySelector('.multi-clear');
    if (clr) clr.addEventListener('click', function(e){
        e.stopPropagation();
        selected.length = 0;
        onChange();
    });
}

// === Рендер таблицы ===
function render(data) {
    var wrap = document.getElementById('hmWrap');
    if (!data.rows || !data.rows.length) {
        wrap.innerHTML = '<div class="empty">Нет задач по выбранным фильтрам</div>';
        return;
    }
    _TT_DATA = {};
    var html = '<table class="hm-table"><thead><tr><th class="task-col">Задача</th>';
    data.days.forEach(function(dk){
        var d = new Date(dk + 'T00:00:00');
        var wd = d.getDay();
        var cls = (wd === 0 || wd === 6) ? ' weekend' : '';
        if (dk === data.today) cls += ' today';
        html += '<th class="' + cls + '">' + fmtD(dk) + '</th>';
    });
    html += '</tr></thead><tbody>';

    data.rows.forEach(function(r){
        html += '<tr><td class="task-cell" title="' + esc(r.name) + '">' + (r.icon || '📋') + ' ' + esc(r.name) + '</td>';
        r.cells.forEach(function(c, idx){
            var pillCls = 'hm-pill ' + (c.status === 'none' ? 'none' : 'st-' + c.status);
            if (c.is_weekend) pillCls += ' is-weekend';
            if (c.hours > 0) {
                var hCls = Math.min(Math.ceil(c.hours / 2), 4);
                if (c.status === 'done') pillCls += ' done-' + hCls;
                else pillCls += ' h-' + hCls;
            }
            var content = c.hours > 0 ? c.hours : '';
            var ttHtml = '';
            if (c.hours > 0 || c.status !== 'none') {
                ttHtml = '<div class="tt-title">' + esc(r.name) + '</div><div style="color:var(--pg-meta);font-size:.7rem;margin-bottom:4px;">' + c.date + '</div>';
                if (c.hours > 0) ttHtml += '<div class="tt-row"><span>Часов:</span><b>' + c.hours + ' ч</b></div>';
                if (c.employees && c.employees.length) ttHtml += '<div class="tt-row"><span>Сотрудники:</span><span style="text-align:right;">' + c.employees.map(esc).join('<br>') + '</span></div>';
            }
            var ttId = 'tt_' + r.id + '_' + idx;
            if (ttHtml) _TT_DATA[ttId] = ttHtml;
            html += '<td class="day-cell"><div class="' + pillCls + '" data-tt="' + ttId + '">' + content + '</div></td>';
        });
        html += '</tr>';
    });
    html += '</tbody></table>';
    wrap.innerHTML = html;

    var ttEl = document.getElementById('hmTooltip');
    wrap.querySelectorAll('.hm-pill').forEach(function(el){
        var ttId = el.getAttribute('data-tt');
        var html = _TT_DATA[ttId];
        if (!html) return;
        el.addEventListener('mouseenter', function(e){ ttEl.innerHTML = html; ttEl.style.display = 'block'; ttEl.style.left = (e.clientX + 15) + 'px'; ttEl.style.top = (e.clientY + 15) + 'px'; });
        el.addEventListener('mousemove', function(e){ ttEl.style.left = (e.clientX + 15) + 'px'; ttEl.style.top = (e.clientY + 15) + 'px'; });
        el.addEventListener('mouseleave', function(){ ttEl.style.display = 'none'; });
    });
}

// === Загрузка ===
function load() {
    document.getElementById('hmWrap').innerHTML = '<div class="empty">Загрузка...</div>';
    var q = '?preset=' + state.preset;
    if (state.preset === 'custom') q += '&from=' + encodeURIComponent(state.from) + '&to=' + encodeURIComponent(state.to);
    
    if (state.depts.length) q += '&department=' + encodeURIComponent(state.depts.join(','));
    if (state.teams.length) q += '&team=' + encodeURIComponent(state.teams.join(','));
    if (state.tags.length) q += '&tag=' + encodeURIComponent(state.tags.join(','));
    
    var task = document.getElementById('fTask').value;
    if (task) q += '&task=' + encodeURIComponent(task);

    fetch('/api/plugins/task_heatmap/data' + q, {credentials: 'same-origin'})
        .then(function(r){ return r.json(); })
        .then(function(d){
            if (!d.success) { document.getElementById('hmWrap').innerHTML = '<div class="empty">Ошибка: ' + esc(d.error) + '</div>'; return; }
            
            if (d.filters) {
                // Отделы
                renderMulti('deptWrap', 'deptDrop', 'deptCnt', d.filters.departments, state.depts, function(){ load(); });
                // Команды
                renderMulti('teamWrap', 'teamDrop', 'teamCnt', d.filters.teams, state.teams, function(){ load(); });
                // Теги
                renderMulti('tagWrap', 'tagDrop', 'tagCnt', d.filters.tags, state.tags, function(){ load(); });
                // Задачи
                var selTask = document.getElementById('fTask');
                if (selTask.options.length <= 1) {
                    d.filters.tasks.forEach(function(x){ selTask.insertAdjacentHTML('beforeend', '<option value="' + x.id + '">' + esc(x.name) + '</option>'); });
                }
            }
            render(d);
        })
        .catch(function(){ document.getElementById('hmWrap').innerHTML = '<div class="empty">Ошибка соединения</div>'; });
}

// === События ===
['deptBtn','teamBtn','tagBtn'].forEach(function(btnId){
    document.getElementById(btnId).addEventListener('click', function(e){
        e.stopPropagation();
        var drop = this.nextElementSibling;
        var isActive = drop.classList.contains('active');
        document.querySelectorAll('.multi-drop').forEach(function(d){ d.classList.remove('active'); });
        if (!isActive) drop.classList.add('active');
    });
});
document.addEventListener('click', function(){
    document.querySelectorAll('.multi-drop').forEach(function(d){ d.classList.remove('active'); });
});

// Пресеты
document.querySelectorAll('.presets button').forEach(function(b){
    b.addEventListener('click', function(){
        document.querySelectorAll('.presets button').forEach(function(x){ x.classList.remove('active'); });
        this.classList.add('active');
        state.preset = this.getAttribute('data-p');
        state.from = ''; state.to = '';
        load();
    });
});

// Применить
document.getElementById('fApply').addEventListener('click', function(){
    var f = document.getElementById('fFrom').value;
    var t = document.getElementById('fTo').value;
    if (!f || !t) return;
    state.preset = 'custom'; state.from = f; state.to = t;
    document.querySelectorAll('.presets button').forEach(function(x){ x.classList.remove('active'); });
    load();
});

document.getElementById('fTask').addEventListener('change', load);

load();
})();
</script>
</body>
</html>'''


def _parse_period(args):
    preset = (args.get('preset') or 'month').strip().lower()
    today = date.today()
    if preset == 'week':
        return today - timedelta(days=today.weekday()), today, 'week'
    if preset == 'month':
        return today.replace(day=1), today, 'month'
    if preset == 'quarter':
        m = (today.month - 1) // 3 * 3 + 1
        return today.replace(month=m, day=1), today, 'quarter'
    if preset == 'year':
        return today.replace(month=1, day=1), today, 'year'
    
    d1 = args.get('from') or ''
    d2 = args.get('to') or ''
    try:
        d1 = datetime.strptime(d1, '%Y-%m-%d').date()
        d2 = datetime.strptime(d2, '%Y-%m-%d').date()
        if d1 <= d2:
            return d1, d2, 'custom'
    except Exception:
        pass
    return today.replace(day=1), today, 'month'


def register(app, db, hooks):
    print(f'[task_heatmap] v{__version__} · {__description__}')

    @app.route('/plugins/task_heatmap/')
    def _th_page():
        try:
            from auth import current_user, user_has
            u = current_user(db)
            if not u: return redirect('/login')
            if not user_has(db, u, 'tab.stats'): return redirect('/')
        except Exception:
            return redirect('/login')
        return Response(_page_html(), mimetype='text/html')

    @app.route('/api/plugins/task_heatmap/data')
    def _th_data():
        try:
            from auth import current_user, user_has
            u = current_user(db)
            if not u: return jsonify({'success': False, 'error': 'auth'}), 401
            if not user_has(db, u, 'tab.stats'): return jsonify({'success': False, 'error': 'forbidden'}), 403
        except Exception:
            return jsonify({'success': False, 'error': 'auth'}), 401

        d1, d2, preset = _parse_period(request.args)
        dept_ids = [x.strip() for x in request.args.get('department', '').split(',') if x.strip()]
        team_ids = [x.strip() for x in request.args.get('team', '').split(',') if x.strip()]
        tag_ids = [x.strip() for x in request.args.get('tag', '').split(',') if x.strip()]
        task_id = request.args.get('task', '')

        data = db.load_all()
        today = date.today().strftime('%Y-%m-%d')

        teams = data.get('teams', [])
        team_members = set()
        if team_ids:
            for t in teams:
                if t['id'] in team_ids:
                    team_members.update(t.get('member_ids') or [])
                    if t.get('manager_id'): team_members.add(t['manager_id'])

        dept_members = set()
        if dept_ids:
            for e in data.get('employees', []):
                if e.get('department_id') in dept_ids:
                    dept_members.add(e['id'])

        tasks = data.get('tasks', [])
        if task_id:
            tasks = [t for t in tasks if t['id'] == task_id]
        
        if dept_ids or team_ids:
            filtered = []
            for t in tasks:
                assigns = t.get('assignees') or []
                if dept_ids and not (set(assigns) & dept_members): continue
                if team_ids and not (set(assigns) & team_members): continue
                filtered.append(t)
            tasks = filtered
            
        if tag_ids:
            filtered = []
            for t in tasks:
                t_tags = t.get('tags') or []
                if any(tag in t_tags for tag in tag_ids):
                    filtered.append(t)
            tasks = filtered

        tasks.sort(key=lambda x: x.get('name', '').lower())

        logs = data.get('log', [])
        logs = [l for l in logs if (l.get('date') or '') >= d1.strftime('%Y-%m-%d') and (l.get('date') or '') <= d2.strftime('%Y-%m-%d')]
        
        if dept_ids or team_ids:
            filtered_logs = []
            for l in logs:
                eid = l.get('employee_id')
                if dept_ids and eid not in dept_members: continue
                if team_ids and eid not in team_members: continue
                filtered_logs.append(l)
            logs = filtered_logs

        log_by_task = {}
        for l in logs:
            tid = l.get('task_id')
            dk = l.get('date')
            if not tid or not dk: continue
            log_by_task.setdefault(tid, {}).setdefault(dk, []).append(l)

        days = []
        cur = d1
        while cur <= d2:
            days.append(cur.strftime('%Y-%m-%d'))
            cur += timedelta(days=1)

        employees = {e['id']: e for e in data.get('employees', [])}
        rows = []
        for t in tasks:
            cells = []
            t_logs = log_by_task.get(t['id'], {})
            for dk in days:
                dt = datetime.strptime(dk, '%Y-%m-%d').date()
                is_wknd = dt.weekday() >= 5
                entries = t_logs.get(dk, [])
                
                hours = sum(float(l.get('hours') or 0) for l in entries)
                status = 'none'
                if entries:
                    prio = {'done': 4, 'in_progress': 3, 'blocked': 2, 'planned': 1}
                    status = max((l.get('status') or 'in_progress' for l in entries), key=lambda s: prio.get(s, 0))
                
                emps = []
                for l in entries:
                    eid = l.get('employee_id')
                    if eid and eid not in emps:
                        e = employees.get(eid)
                        emps.append(e.get('name', eid) if e else eid)

                cells.append({
                    'date': dk,
                    'hours': round(hours * 4) / 4,
                    'status': status,
                    'is_weekend': is_wknd,
                    'employees': emps[:5]
                })
            
            rows.append({
                'id': t['id'],
                'name': t.get('name', ''),
                'icon': t.get('icon', '📋'),
                'cells': cells
            })

        # Сбор тегов
        all_tags = set()
        for t in data.get('tasks', []):
            for tg in (t.get('tags') or []):
                all_tags.add(tg)

        all_depts = [{'id': d['id'], 'name': d.get('name', '')} for d in data.get('departments', [])]
        all_teams = [{'id': t['id'], 'name': t.get('name', '')} for t in teams]
        all_tasks = [{'id': t['id'], 'name': t.get('name', '')} for t in data.get('tasks', []) if t.get('status') != 'archived']

        return jsonify({
            'success': True,
            'days': days,
            'rows': rows,
            'today': today,
            'filters': {
                'departments': all_depts,
                'teams': all_teams,
                'tasks': all_tasks,
                'tags': [{'id': t, 'name': '#'+t} for t in sorted(all_tags)]
            }
        })

    def on_startup(**ctx):
        print('[task_heatmap] готов — /plugins/task_heatmap/')

    hooks.on('on_startup', on_startup)
