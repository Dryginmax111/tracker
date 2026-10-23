"""plugins/daily_report.py — 🌅 Отчёт за день, v1.0 (патч v1.1.8).

Плагин меню «Статистика»: красивый информативный отчёт за выбранный день.
  * KPI-плитки: часы всего / отметок / сотрудников в деле / % закрытых задач
  * разбивка по отделам и командам с прогресс-барами
  * таблица сотрудников: часы, число отметок, статус присутствия (отпуск/больничный…)
  * лента отметок дня с задачей, временем, тегами, ссылками и приказами
Поддержка светлой/тёмной темы через plugin_theme.js.
"""
__version__ = '1.0'
__description__ = '🌅 Отчёт за день: KPI, отделы, сотрудники, лента отметок'

from datetime import date, datetime

from flask import jsonify, request, Response, redirect


def _esc(s):
    return (str(s if s is not None else '')
            .replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


_ABSENCE_ICONS = {
    'vacation': '🏖', 'sick_leave': '🤒',
    'business_trip': '✈️', 'remote': '🏠',
}


def _valid_date(s):
    try:
        datetime.strptime(s, '%Y-%m-%d')
        return True
    except Exception:
        return False


# ============================================================
# JS — регистрация пункта в меню «Статистика»
# ============================================================
_JS = r'''
(function(){
'use strict';
function register(){
    if (typeof window.__trkRegisterPlugin !== 'function') {
        setTimeout(register, 200);
        return;
    }
    window.__trkRegisterPlugin({
        id: 'daily_report',
        icon: '🌅',
        name: 'Отчёт за день',
        url: '/plugins/daily_report/',
        perm: 'plugin.daily_report.use'
    });
}
register();
})();
'''


# ============================================================
# HTML страницы отчёта
# ============================================================
def _page_html():
    return r'''<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>🌅 Отчёт за день</title>
<script src="/static/plugin_theme.js"></script>
<style>
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;margin:0;padding:16px;
  font-size:14px;background:var(--pg-bg,#0d1117);color:var(--pg-text,#e6edf3);min-height:100vh}
.w{max-width:1400px;margin:0 auto;display:flex;flex-direction:column;gap:14px}
.head{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:14px 18px;
  background:var(--pg-card-bg,#161b22);border:1px solid var(--pg-card-border,#232a33);border-radius:14px}
.head h1{margin:0;font-size:1.2rem;font-weight:800;color:var(--pg-accent,#00897b)}
.back{color:var(--pg-desc,#9aa7b3);text-decoration:none;padding:6px 14px;border:1px solid var(--pg-card-border,#232a33);
  border-radius:20px;font-size:.85rem}
.back:hover{background:var(--pg-accent-bg,rgba(0,137,123,.14));color:var(--pg-accent,#00897b)}
.daynav{margin-left:auto;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.daynav button{padding:6px 10px;border:1px solid var(--pg-card-border,#232a33);background:transparent;
  color:var(--pg-desc,#9aa7b3);border-radius:8px;cursor:pointer;font-family:inherit;font-weight:700}
.daynav button:hover{color:var(--pg-accent,#00897b);border-color:var(--pg-accent,#00897b)}
.daynav input[type=date]{padding:6px 8px;border-radius:8px;border:1px solid var(--pg-input-border,#2c3644);
  background:var(--pg-input-bg,#1a2027);color:var(--pg-text,#e6edf3);font-family:inherit}
.holiday-pill{padding:4px 12px;border-radius:16px;background:#8e2438;color:#fff;font-weight:700;font-size:.8rem}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.kpi{background:var(--pg-card-bg,#161b22);border:1px solid var(--pg-card-border,#232a33);border-radius:14px;
  padding:14px 16px;display:flex;flex-direction:column;gap:2px}
.kpi .v{font-size:1.5rem;font-weight:800;color:var(--pg-accent,#00897b)}
.kpi .l{font-size:.74rem;color:var(--pg-meta,#6e7c8a);text-transform:uppercase;letter-spacing:.04em}
.kpi.warn .v{color:#f5a623}.kpi.bad .v{color:#ec7063}.kpi.good .v{color:#58d68d}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
.card{background:var(--pg-card-bg,#161b22);border:1px solid var(--pg-card-border,#232a33);border-radius:14px;padding:14px 16px}
.card h2{margin:0 0 10px;font-size:.95rem;font-weight:800;color:var(--pg-text,#e6edf3)}
.bar-row{display:flex;align-items:center;gap:8px;margin-bottom:8px;font-size:.82rem}
.bar-name{width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--pg-desc,#9aa7b3)}
.bar-track{flex:1;height:10px;border-radius:6px;background:var(--pg-inner-bg,#10151c);overflow:hidden}
.bar-fill{height:100%;border-radius:6px;background:linear-gradient(90deg,var(--pg-accent,#00897b),#26a69a)}
.bar-val{width:70px;text-align:right;font-weight:700}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{text-align:left;padding:7px 8px;color:var(--pg-meta,#6e7c8a);font-weight:700;border-bottom:1px solid var(--pg-card-border,#232a33);
  text-transform:uppercase;font-size:.68rem;letter-spacing:.05em;position:sticky;top:0;background:var(--pg-card-bg,#161b22)}
td{padding:7px 8px;border-bottom:1px solid rgba(128,128,128,.12)}
tr:hover td{background:rgba(0,137,123,.06)}
.st-chip{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.7rem;font-weight:700;margin-left:4px}
.st-vacation{background:rgba(245,215,110,.16);color:#f5d76e}
.st-sick_leave{background:rgba(236,112,99,.16);color:#ec7063}
.st-business_trip{background:rgba(93,173,226,.16);color:#5dade2}
.st-remote{background:rgba(88,214,141,.16);color:#58d68d}
.feed-item{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid rgba(128,128,128,.12)}
.feed-item:last-child{border-bottom:none}
.feed-avatar{width:32px;height:32px;border-radius:50%;flex:none;display:flex;align-items:center;justify-content:center;
  color:#fff;font-weight:800;font-size:.68rem}
.feed-body{flex:1;min-width:0}
.feed-top{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.feed-name{font-weight:700;font-size:.85rem}
.feed-task{color:var(--pg-accent,#00897b);font-weight:700;font-size:.82rem}
.feed-hours{margin-left:auto;font-weight:800;font-size:.9rem}
.feed-comment{color:var(--pg-desc,#9aa7b3);font-size:.8rem;margin-top:3px;white-space:pre-wrap;word-break:break-word}
.feed-tags{margin-top:4px;display:flex;gap:6px;flex-wrap:wrap}
.feed-tag{font-size:.68rem;padding:2px 8px;border-radius:9px;background:var(--pg-accent-bg,rgba(0,137,123,.14));
  color:var(--pg-accent,#00897b);text-decoration:none}
.empty{padding:24px;text-align:center;color:var(--pg-meta,#6e7c8a)}
.msg{padding:8px 12px;border-radius:8px;font-size:.85rem;display:none}
.msg.err{display:block;background:rgba(236,112,99,.12);color:#ec7063}
.scroll{max-height:420px;overflow:auto}
</style></head>
<body><div class="w">
  <div class="head">
    <a class="back" href="/">← К трекеру</a>
    <h1>🌅 Отчёт за день</h1>
    <span class="holiday-pill" id="holPill" style="display:none;"></span>
    <div class="daynav">
      <button id="prevDay" title="Предыдущий день">◀</button>
      <input type="date" id="dayPick">
      <button id="nextDay" title="Следующий день">▶</button>
      <button id="todayBtn">Сегодня</button>
    </div>
  </div>
  <div class="msg" id="errMsg"></div>
  <div class="kpis" id="kpis"></div>
  <div class="grid2">
    <div class="card"><h2>🏢 По отделам</h2><div id="deptBars"><div class="empty">Загрузка…</div></div></div>
    <div class="card"><h2>👥 По командам</h2><div id="teamBars"><div class="empty">—</div></div></div>
  </div>
  <div class="card"><h2>🧑‍💼 Сотрудники</h2><div class="scroll"><table id="empTable"><thead>
    <tr><th>Сотрудник</th><th>Отдел</th><th>Часов</th><th>Отметок</th><th>Статус</th></tr>
    </thead><tbody></tbody></table></div></div>
  <div class="card"><h2>📝 Лента отметок</h2><div id="feed"><div class="empty">Загрузка…</div></div></div>
</div>
<script>
'use strict';
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function fmtH(v){v=Math.round((v||0)*10)/10;return (v%1===0? v.toFixed(0): v.toFixed(1))+' ч';}
function isoToday(){var d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
function shiftDay(iso,n){var p=iso.split('-');var d=new Date(+p[0],+p[1]-1,+p[2]);d.setDate(d.getDate()+n);
  return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
var pick=document.getElementById('dayPick');pick.value=isoToday();
function err(m){var e=document.getElementById('errMsg');e.className='msg err';e.textContent=m;}
function load(){
  err('');document.getElementById('errMsg').className='msg';
  fetch('/api/plugins/daily_report/data?date='+encodeURIComponent(pick.value),{credentials:'same-origin'})
  .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})
  .then(function(d){
    if(!d.success){err(d.error||'Ошибка загрузки');return;}
    render(d);
  }).catch(function(e){err('Не удалось загрузить отчёт: '+e.message);});
}
function kpiCard(v,l,cls){return '<div class="kpi '+(cls||'')+'"><div class="v">'+esc(v)+'</div><div class="l">'+esc(l)+'</div></div>';}
function bars(elId,items,total){
  var el=document.getElementById(elId);
  if(!items.length){el.innerHTML='<div class="empty">Нет данных за этот день</div>';return;}
  el.innerHTML=items.map(function(it){
    var pct=total>0?Math.min(100,Math.round(it.hours/total*100)):0;
    return '<div class="bar-row"><div class="bar-name" title="'+esc(it.name)+'">'+esc(it.name)+'</div>'+
      '<div class="bar-track"><div class="bar-fill" style="width:'+pct+'%"></div></div>'+
      '<div class="bar-val">'+fmtH(it.hours)+'</div></div>';
  }).join('');
}
function initials(n){var p=String(n||'').trim().split(/\s+/);return ((p[0]||'?')[0]+(p[1]?p[1][0]:'')).toUpperCase();}
function render(d){
  var k=d.kpi;
  document.getElementById('kpis').innerHTML=
    kpiCard(fmtH(k.hours),'часов отмечено')+
    kpiCard(k.logs,'отметок')+
    kpiCard(k.active_emps+' / '+k.emps,'сотрудников в деле')+
    kpiCard(k.done_today,'задач закрыто',k.done_today>0?'good':'')+
    kpiCard(k.open_overdue,'просрочено открытых',k.open_overdue>0?'bad':'')+
    kpiCard((k.avg_per_person||0).toFixed(1)+' ч','средне на человека',k.hours>0&&k.avg_per_person<6?'warn':'');
  var hp=document.getElementById('holPill');
  if(d.holiday){hp.style.display='';hp.textContent='🎉 '+d.holiday;}else hp.style.display='none';
  bars('deptBars',d.departments,k.hours);
  bars('teamBars',d.teams,k.hours);
  var tb=document.querySelector('#empTable tbody');
  tb.innerHTML=d.employees.map(function(e){
    var chips=(e.absences||[]).map(function(a){return '<span class="st-chip st-'+esc(a.type)+'">'+esc(a.icon)+' '+esc(a.label)+'</span>';}).join('');
    if(!e.hours&&!e.logs&&!chips)chips='<span class="st-chip" style="background:rgba(128,128,128,.15);color:var(--pg-meta)">нет активности</span>';
    return '<tr><td><b>'+esc(e.name)+'</b></td><td>'+esc(e.department||'—')+'</td><td>'+fmtH(e.hours)+'</td><td>'+e.logs+'</td><td>'+chips+'</td></tr>';
  }).join('')||'<tr><td colspan="5" class="empty">Нет сотрудников</td></tr>';
  var feed=document.getElementById('feed');
  if(!d.feed.length){feed.innerHTML='<div class="empty">За этот день отметок нет</div>';}
  else feed.innerHTML=d.feed.map(function(f){
    var tags='';
    (f.links||[]).forEach(function(l){tags+='<a class="feed-tag" target="_blank" rel="noopener" href="'+esc(l.url||'#')+'">🔗 '+esc(l.description||(l.url||''))+'</a>';});
    (f.orders||[]).forEach(function(o){tags+='<span class="feed-tag">📄 '+esc(o.description||'')+(o.value?(' · '+esc(o.value)):'')+'</span>';});
    (f.extra_data||[]).forEach(function(x){tags+='<span class="feed-tag">ℹ️ '+esc(typeof x==='string'?x:(x.text||x.name||JSON.stringify(x)))+'</span>';});
    return '<div class="feed-item"><div class="feed-avatar" style="background:'+esc(f.color||'#888')+'">'+esc(initials(f.emp_name))+'</div>'+
      '<div class="feed-body"><div class="feed-top"><span class="feed-name">'+esc(f.emp_name)+'</span>'+
      '<span class="feed-task">'+esc(f.task_icon||'📋')+' '+esc(f.task_name)+'</span>'+
      '<span class="feed-hours">'+fmtH(f.hours)+'</span></div>'+
      (f.comment?'<div class="feed-comment">'+esc(f.comment)+'</div>':'')+
      (tags?'<div class="feed-tags">'+tags+'</div>':'')+
      '<div style="font-size:.66rem;color:var(--pg-meta);margin-top:2px;">⏱ '+esc(f.time||'')+'</div>'+
      '</div></div>';
  }).join('');
}
document.getElementById('prevDay').onclick=function(){pick.value=shiftDay(pick.value,-1);load();};
document.getElementById('nextDay').onclick=function(){pick.value=shiftDay(pick.value,1);load();};
document.getElementById('todayBtn').onclick=function(){pick.value=isoToday();load();};
pick.addEventListener('change',load);
load();
</script></body></html>'''


# ============================================================
# Регистрация
# ============================================================
def register(app, db, hooks):
    print('[daily_report] v' + __version__ + ' · ' + __description__)

    @app.route('/plugins-assets/daily_report.js', methods=['GET'])
    def _dr_js():
        return app.response_class(_JS, mimetype='application/javascript')

    def _auth():
        # PATCH v1.1.9: не глотать исключения молча — печатать причину,
        # иначе «Отчёт за день» выглядит как «не работает» без следов в логе.
        try:
            from auth import current_user, user_has
            u = current_user(db)
            if not u:
                return None
            if not user_has(db, u, 'plugin.daily_report.use'):
                print('[daily_report] отказано в доступе: у пользователя нет права plugin.daily_report.use')
                return None
            return u
        except Exception:
            import traceback
            print('[daily_report] ошибка авторизации:')
            traceback.print_exc()
            return None

    @app.route('/plugins/daily_report/', methods=['GET'])
    def _dr_page():
        if not _auth():
            return redirect('/login')
        return Response(_page_html(), mimetype='text/html')

    @app.route('/api/plugins/daily_report/selftest', methods=['GET'])
    def _dr_selftest():
        """PATCH v1.1.9: диагностика — почему «не работает»: auth / routes / data."""
        import traceback as _tb
        out = {'plugin_version': __version__}
        try:
            from auth import current_user, user_has
            u = current_user(db)
            out['logged_in'] = bool(u)
            out['user'] = (u or {}).get('username')
            out['perm_ok'] = bool(u and user_has(db, u, 'plugin.daily_report.use'))
        except Exception:
            out['auth_error'] = _tb.format_exc(limit=2)
        try:
            rules = sorted(str(r.rule) for r in app.url_map.iter_rules() if 'daily_report' in str(r))
            out['routes'] = rules
        except Exception:
            out['routes_error'] = _tb.format_exc(limit=2)
        try:
            day = date.today().strftime('%Y-%m-%d')
            d = db.load_all(since=day)
            out['db_ok'] = True
            out['today_logs'] = len([l for l in d.get('log', []) if (l.get('date') or '') == day])
        except Exception:
            out['db_ok'] = False
            out['db_error'] = _tb.format_exc(limit=3)
        return jsonify(out)

    @app.route('/api/plugins/daily_report/data', methods=['GET'])
    def _dr_data():
        if not _auth():
            return jsonify({'success': False, 'error': 'auth'}), 401
        day = (request.args.get('date') or '').strip()
        if not _valid_date(day):
            day = date.today().strftime('%Y-%m-%d')

        try:
            # PATCH v1.1.9: since=day — читаем только логи этого дня (без кэша
            # и без полного слепка всех work_logs — быстрее и меньше памяти).
            data = db.load_all(since=day)
        except Exception:
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'error': 'internal: ' + str(traceback.format_exc(limit=1))}), 500
        employees = data.get('employees', [])
        emp_by_id = {e['id']: e for e in employees}
        dept_by_id = {d['id']: d for d in data.get('departments', [])}
        tasks = data.get('tasks', [])
        task_by_id = {t['id']: t for t in tasks}
        logs = [l for l in data.get('log', []) if (l.get('date') or '') == day]

        # часы по сотрудникам / отделам / командам
        emp_hours = {}
        emp_logs = {}
        feed = []
        for l in logs:
            eid = l.get('employee_id')
            h = float(l.get('hours') or 0)
            emp_hours[eid] = emp_hours.get(eid, 0.0) + h
            emp_logs[eid] = emp_logs.get(eid, 0) + 1
            t = task_by_id.get(l.get('task_id')) or {}
            feed.append({
                'emp_name': (emp_by_id.get(eid) or {}).get('name', '—'),
                'color': (emp_by_id.get(eid) or {}).get('color', '#888'),
                'task_name': t.get('name', '—'),
                'task_icon': t.get('icon', '📋'),
                'hours': h,
                'comment': l.get('comment') or '',
                'time': (l.get('created_at') or '')[-8:-3] if l.get('created_at') else '',
                'links': l.get('links') or [],
                'orders': l.get('orders') or [],
                'extra_data': l.get('extra_data') or [],
            })
        feed.sort(key=lambda f: f['time'], reverse=True)

        dept_hours, team_hours = {}, {}
        for e in employees:
            h = emp_hours.get(e['id'], 0.0)
            if not h:
                continue
            # PATCH v1.1.9: db.load_all уже кладёт имя отдела в e['department']
            dn_name = e.get('department') or (dept_by_id.get(e.get('department_id') or '') or {}).get('name', '')
            if dn_name:
                dept_hours[dn_name] = dept_hours.get(dn_name, 0.0) + h
        for tm in data.get('teams', []):
            th = sum(emp_hours.get(mid, 0.0) for mid in tm.get('member_ids', []))
            if th:
                team_hours[tm['name']] = th

        total_hours = sum(emp_hours.values())
        active_emps = len([1 for v in emp_hours.values() if v > 0])
        done_today = sum(1 for t in tasks
                         if (t.get('completed_at') or '').startswith(day))
        today_iso = day
        open_overdue = sum(1 for t in tasks
                           if t.get('status') == 'active'
                           and (t.get('deadline') or '') and t['deadline'] < today_iso)

        absents = {}
        for e in employees:
            for v in e.get('vacations') or []:
                if (v.get('from') or '') <= day <= (v.get('to') or ''):
                    absents.setdefault(e['id'], []).append({
                        'type': v.get('type') or 'vacation',
                        'icon': _ABSENCE_ICONS.get(v.get('type') or 'vacation', '•'),
                        'label': {'vacation': 'Отпуск', 'sick_leave': 'Больничный',
                                  'business_trip': 'Командировка', 'remote': 'Удалёнка'}
                        .get(v.get('type') or 'vacation', 'Отсутствие'),
                    })

        emp_rows = [{
            'name': e.get('name', ''),
            'department': (dept_by_id.get(e.get('department_id') or '') or {}).get('name', ''),
            'hours': round(emp_hours.get(e['id'], 0.0), 1),
            'logs': emp_logs.get(e['id'], 0),
            'absences': absents.get(e['id'], []),
        } for e in employees if not e.get('fired_date')]
        emp_rows.sort(key=lambda r: (-r['hours'], r['name'].lower()))

        holidays = data.get('holidays') or {}
        return jsonify({
            'success': True,
            'date': day,
            'holiday': holidays.get(day, ''),
            'kpi': {
                'hours': round(total_hours, 1),
                'logs': len(logs),
                'active_emps': active_emps,
                'emps': len(emp_rows),
                'done_today': done_today,
                'open_overdue': open_overdue,
                'avg_per_person': (total_hours / active_emps) if active_emps else 0.0,
            },
            'departments': [{'name': k, 'hours': round(v, 1)}
                            for k, v in sorted(dept_hours.items(), key=lambda kv: -kv[1])],
            'teams': [{'name': k, 'hours': round(v, 1)}
                      for k, v in sorted(team_hours.items(), key=lambda kv: -kv[1])],
            'employees': emp_rows,
            'feed': feed[:200],
        })
