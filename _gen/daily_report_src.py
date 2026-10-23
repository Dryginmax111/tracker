#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_report — Отчёт за день (плагин меню «Статистика»). v1.1.8"""
__version__ = '1.0.0'
__description__ = 'Отчёт за день: KPI, отделы, сотрудники, лента отметок'
__author__ = 'reestr'
__enabled__ = True

from datetime import datetime, date
from flask import jsonify, request, Response, redirect

_CSS_VARS = """
:root{--pg-bg:#0d1117;--pg-card-bg:#161b22;--pg-card-border:#232a33;--pg-text:#e6edf3;
--pg-desc:#9aa7b3;--pg-meta:#6e7c8a;--pg-accent:#00897b;--pg-accent-2:#26a69a;--pg-accent-bg:rgba(0,137,123,.14);
--pg-input-bg:#1a2027;--pg-red:#ec7063;--pg-yellow:#f5d76e;--pg-blue:#5dade2;--pg-green:#58d68d}
"""

_page = None

def _page_html():
    global _page
    if _page is not None:
        return _page
    _page = '''<!DOCTYPE html>
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
function avColor(n){var h=0,s=String(n||'?');for(var i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))%360;return 'hsl('+h+',45%,40%)';}
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


_JS = """
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
"""


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
    hol = (st.get('holidays') or {}).get(day)
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
        expected = 1 if (not hol and (not atype or atype in ('business_trip', 'remote'))) else 0
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
           'present': present, 'expected': len(emp_rows),
           'closed': len(closed_ids), 'overdue': overdue, 'absent': len(absent)}
    emp_rows.sort(key=lambda r: (-r['hours'], r['name']))
    return {'date': day, 'holiday': hol or '', 'kpi': kpi, 'departments': dlist,
            'employees': emp_rows, 'absent': absent, 'feed': feed[:120]}


def register(app, db, hooks):
    print('[daily_report] v' + __version__ + ' · ' + __description__)

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
            out = {'success': True}
            out.update(_build(db, raw))
            return jsonify(out)
        except Exception as ex:
            return jsonify({'success': False, 'error': str(ex)[:200]}), 500
