"""V208: one 작업도면 with three views (작업전 / 작업중 / 작업후) in HTML.

The app already keeps two drawings for a job: 현장반영 (before.sqlite3) and
후도면 (after.sqlite3, a copy of 현장반영 with the new routes). This module puts
them on one drawing and keeps, for every core slot (cable id + number), the
작업전 assignment (현장반영) and the 작업후 assignment (후도면) side by side:

- a cable has one role: 기설 / 철거 / 절단 / 신설
- 작업전 shows 기설 + 철거·절단 with the 작업전 assignment
- 작업후 shows 기설 + 신설 with the 작업후 assignment
- 작업중 shows everything; a 기설 slot whose number changed is 코어절체
  (5번: 5 → 3), not an error. Unchanged slots are 유지.

Duplicate / error checks run inside each view only, with the app's existing
rules (completion_report, error_core_summary). Nothing here writes a drawing.
"""


WORK_VIEW_FILE='도면_작업도면_전중후.html'
WORK_VIEW_MODES=(('before','작업전'),('during','작업중'),('after','작업후'))
WORK_VIEW_REMOVED=('철거','절단')
WORK_VIEW_VISIBLE={'before':('기설','철거','절단'),'during':('기설','철거','절단','신설'),'after':('기설','신설')}
WORK_VIEW_CHANGED=('코어절체','해제','신규배정')


def work_view_key(value):
    return str(value or '').strip().casefold()


def work_view_role(before_status,after_status,has_after=True):
    """Role of a cable on the 작업도면. None = the cable is not in that drawing."""
    b=None if before_status is None else (str(before_status or '').strip() or '기설')
    a=None if after_status is None else (str(after_status or '').strip() or '기설')
    statuses={s for s in (b,a) if s}
    if '절단' in statuses:return '절단'
    if '철거' in statuses:return '철거'
    if has_after and b is not None and a is None:return '철거'  # deleted in 후도면
    if b is None or '신설' in statuses:return '신설'
    return '기설'


def work_view_node_role(before_status,after_status,has_after=True):
    role=work_view_role(before_status,after_status,has_after)
    return '기설' if role=='절단' else role


def work_view_state(role,before_id,after_id):
    """What happens to one core slot between 작업전 and 작업후."""
    b=str(before_id or '').strip();a=str(after_id or '').strip()
    if role=='신설':return '신설' if a else ''
    if role in WORK_VIEW_REMOVED:return role if b else ''
    if b and a:return '유지' if work_view_key(b)==work_view_key(a) else '코어절체'
    if b:return '해제'
    if a:return '신규배정'
    return ''


def _work_view_rows(store,cable_id):
    try:return {int(r['core_index']):dict(r) for r in store.cores(cable_id)}
    except Exception:return {}


def _work_view_done(report,slot):
    entry=((report or {}).get('by_slot') or {}).get(slot)
    if entry is None:return None,''
    if not entry.get('required',True):return None,str(entry.get('excluded_reason') or '')[:200]
    done=bool(entry.get('complete'));return done,('' if done else str(entry.get('reason') or '')[:200])


def work_view_errors(store):
    """{(cable id, number): reason} from the app's 오류코어 rules."""
    found={}
    if store is None:return found
    try:entries=store.error_core_summary()['entries']
    except Exception:return found
    for entry in entries:
        slot=entry.get('slot')
        try:key=(str(slot[0]),int(slot[1]))
        except (TypeError,ValueError,IndexError):continue
        try:reason=str(entry['row'][2] or '')
        except Exception:reason=''
        found.setdefault(key,(reason or '오류코어')[:200])
    return found


def _work_view_report(store):
    if store is None:return {}
    try:return completion_report(store)
    except Exception:return {}


def _work_view_phases(store,core):
    try:return [work_phase_short(n) for n in phase_names(store,core)]
    except Exception:return []


def work_view_data(before,after,work=None):
    """Both drawings as one 작업도면. before/after are Store objects; after may
    be None (후도면 not made yet: 작업후 then shows the 현장반영 assignment)."""
    has_after=after is not None
    b_cables={str(c['id']):dict(c) for c in before.cables()}
    a_cables={str(c['id']):dict(c) for c in after.cables()} if has_after else {}
    b_nodes={str(n['id']):dict(n) for n in before.nodes()}
    a_nodes={str(n['id']):dict(n) for n in after.nodes()} if has_after else {}
    methods=html_view_methods(work)
    b_report=_work_view_report(before);a_report=_work_view_report(after) if has_after else {}
    b_errors=work_view_errors(before);a_errors=work_view_errors(after) if has_after else {}
    nodes=[]
    for nid in list(b_nodes)+[k for k in a_nodes if k not in b_nodes]:
        bn=b_nodes.get(nid);an=a_nodes.get(nid)
        role=work_view_node_role(bn['status'] if bn else None,an['status'] if an else None,has_after)
        nodes.append(dict(id=nid,role=role,row=an or bn,rows=dict(before=bn,after=an)))
    cables=[];cores={}
    for cid in list(b_cables)+[k for k in a_cables if k not in b_cables]:
        bc=b_cables.get(cid);ac=a_cables.get(cid)
        role=work_view_role(bc['status'] if bc else None,ac['status'] if ac else None,has_after)
        row=ac or bc;cables.append(dict(id=cid,role=role,row=row,in_before=bool(bc),in_after=bool(ac),rows=dict(before=bc,after=ac)))
        b_rows=_work_view_rows(before,cid) if bc else {}
        a_rows=(_work_view_rows(after,cid) if ac else {}) if has_after else b_rows
        phase_store=after if (has_after and ac) else before
        size=max([int(row.get('size') or 0)]+list(b_rows)+list(a_rows))
        result=[]
        for n in range(1,size+1):
            b=b_rows.get(n,{});a=a_rows.get(n,{});slot=(cid,n)
            bid=str(b.get('core_id') or '').strip();aid=str(a.get('core_id') or '').strip()
            db,rb=_work_view_done(b_report,slot) if bc else (None,'')
            da,ra=_work_view_done(a_report,slot) if (has_after and ac) else (None,'')
            result.append(dict(n=n,b=bid,bd=str(b.get('detail') or ''),a=aid,ad=str(a.get('detail') or ''),
                               s=work_view_state(role,bid,aid),m=methods.get(slot,''),db=db,rb=rb,da=da,ra=ra,
                               eb=b_errors.get(slot,'') if bc else '',ea=a_errors.get(slot,'') if (has_after and ac) else '',
                               ph=_work_view_phases(phase_store,a if (has_after and ac) else b) if (aid or bid) else []))
        cores[cid]=result
    issues=work_view_issues(cables,cores)
    return dict(has_after=has_after,nodes=nodes,cables=cables,cores=cores,issues=issues,
                counts=work_view_counts(cables,cores,work,issues))


def work_view_issues(cables,cores):
    """Problems inside each view only. A slot that differs between 작업전 and
    작업후 is never an issue by itself (that is 코어절체)."""
    issues={'before':[],'after':[],'broken':[]}
    for view,field,error in (('before','b','eb'),('after','a','ea')):
        for cable in cables:
            if cable['role'] not in WORK_VIEW_VISIBLE[view]:continue
            seen={}
            for r in cores.get(cable['id'],()):
                if r[field]:seen.setdefault(work_view_key(r[field]),[]).append(r)
            for group in seen.values():
                if len(group)>1:
                    numbers=[r['n'] for r in group]
                    issues[view].append(dict(kind='중복',cable=cable['id'],n=numbers,id=group[0][field],
                                             text=f"같은 코어ID가 한 케이블 {len(numbers)}칸에 배정 ({', '.join(map(str,numbers))}번)"))
            for r in cores.get(cable['id'],()):
                if r[error]:issues[view].append(dict(kind='오류',cable=cable['id'],n=[r['n']],id=r[field],text=r[error]))
    after_ids=set()
    for cable in cables:
        if cable['role'] in WORK_VIEW_VISIBLE['after']:
            after_ids.update(work_view_key(r['a']) for r in cores.get(cable['id'],()) if r['a'])
    broken={}
    for cable in cables:
        if cable['role'] not in WORK_VIEW_REMOVED:continue
        for r in cores.get(cable['id'],()):
            key=work_view_key(r['b'])
            if key and key not in after_ids and key not in broken:
                broken[key]=dict(kind='끊김',cable=cable['id'],n=[r['n']],id=r['b'],text=f"{cable['role']} 케이블의 코어인데 작업후 경로가 없음")
    issues['broken']=list(broken.values())
    return issues


def work_view_counts(cables,cores,work=None,issues=None):
    roles={};states={}
    for cable in cables:
        roles[cable['role']]=roles.get(cable['role'],0)+1
        for r in cores.get(cable['id'],()):
            if r['s']:states[r['s']]=states.get(r['s'],0)+1
    method_ids={}
    for row in (work or {}).get('rows') or ():
        method=str(row.get('method') or '')
        if method:method_ids.setdefault(method,set()).add(work_view_key(row.get('core_id')) or id(row))
    done_by_id={}
    for cable in cables:
        if cable['role'] not in WORK_VIEW_VISIBLE['after']:continue
        for r in cores.get(cable['id'],()):
            if r['a'] and r['da'] is not None:
                key=work_view_key(r['a']);done_by_id[key]=done_by_id.get(key,True) and bool(r['da'])
    issues=issues or {}
    return dict(roles=roles,states=states,cut=len(method_ids.get('절단절체',())),transfer=len(method_ids.get('코어절체',())),
                after_total=len(done_by_id),after_done=sum(1 for v in done_by_id.values() if v),
                before_issues=len(issues.get('before',())),after_issues=len(issues.get('after',())),broken=len(issues.get('broken',())))


def work_view_document(scene,meta):
    import html as _html
    data=dict(scene,meta=meta)
    title=_html.escape('작업도면 전·중·후 · '+str(meta.get('name') or ''))
    return WORK_VIEW_TEMPLATE.replace('__TITLE__',title).replace('__DATA__',html_view_json(data))


WORK_VIEW_TEMPLATE=r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --navy:#101d33;--navy-3:#22375a;--line:#dbe3ed;--line-2:#e8eef5;--bg:#f3f6fa;--paper:#fff;
  --ink:#172033;--ink-2:#475569;--ink-3:#64748b;--ink-4:#94a3b8;--accent:#2f5fc4;
  --ok:#15803d;--bad:#c62828;--need:#ff1744;
  --old:#1565c0;--rem:#424242;--cut:#d32f2f;--new:#f59e0b;--xfer:#7c3aed;
  --font:"Malgun Gothic","맑은 고딕","Pretendard","Noto Sans KR","Noto Sans CJK KR",system-ui,sans-serif;
  --mono:"D2Coding","Consolas","Noto Sans Mono",ui-monospace,monospace;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{font-family:var(--font);color:var(--ink);background:var(--bg);font-size:13px;overflow:hidden}
button,input{font:inherit;color:inherit}
button{cursor:pointer}
.app{display:grid;grid-template-rows:auto auto 1fr auto;height:100vh}
.mode-strip{background:var(--vc,#315eac);color:#fff;font-weight:700;font-size:12px;padding:5px 16px;display:flex;gap:10px;align-items:center;transition:background .2s}
.mode-strip .right{margin-left:auto;font-weight:500;opacity:.9}
header.top{background:var(--navy);color:#fff;display:grid;grid-template-columns:auto 1fr auto;align-items:center;column-gap:24px;padding:10px 16px 0}
.brand{display:flex;align-items:center;gap:10px;padding-bottom:10px}
.brand b{font-size:17px;display:block}
.brand small{font-size:11px;color:#8ea3c4;display:block;margin-top:1px}
.file{display:flex;align-items:center;gap:10px;padding-bottom:10px;min-width:0}
.file .name{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.file .when{font-size:11px;color:#8ea3c4;white-space:nowrap}
.actions{display:flex;gap:6px;padding-bottom:10px;align-items:center}
.search{display:flex;align-items:center;background:var(--navy-3);border:1px solid #2f4a74;border-radius:6px;padding:0 8px}
.search input{background:none;border:0;outline:0;color:#fff;padding:7px 4px;width:180px;font-size:12px}
.search input::placeholder{color:#8ea3c4}
.btn-top{background:var(--navy-3);border:1px solid #2f4a74;color:#e6eefb;border-radius:6px;padding:7px 12px;font-size:12px;white-space:nowrap}
.btn-top:hover{background:#2b4570}
.readonly{font-size:11px;font-weight:700;color:#ffd166;border:1px solid #6b5a2a;border-radius:999px;padding:4px 10px;white-space:nowrap}
.views{grid-column:1/-1;display:flex;margin:0 -16px;padding:0 16px;border-top:1px solid #1d2f4f}
.view{flex:1;border:0;background:none;display:flex;align-items:center;gap:10px;justify-content:center;padding:9px 6px 10px;color:#8ea3c4;font-size:13px;position:relative;white-space:nowrap}
.view .n{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font-size:11px;font-weight:700;border:1.5px solid #3a5582}
.view small{font-size:11px;color:#6f86ab;font-weight:500}
.view:hover{color:#dbe6f7}
.view.on{color:#fff;font-weight:700;background:rgba(255,255,255,.07)}
.view.on .n{background:var(--vc);border-color:var(--vc);color:#fff}
.view.on small{color:#c8d6ee}
.view.on::after{content:"";position:absolute;left:12%;right:12%;bottom:0;height:3px;border-radius:3px 3px 0 0;background:var(--vc)}
.body{display:grid;grid-template-columns:1fr 440px;min-height:0}
.canvas-wrap{position:relative;min-width:0;overflow:hidden;background:radial-gradient(circle at 1px 1px,#d5dde8 1px,transparent 1.2px) 0 0/24px 24px,#f7f9fc}
svg.map{position:absolute;inset:0;width:100%;height:100%;cursor:grab;user-select:none}
svg.map.drag{cursor:grabbing}
.float{position:absolute;background:var(--paper);border:1px solid var(--line);border-radius:10px;box-shadow:0 6px 24px rgba(16,29,51,.08),0 1px 2px rgba(16,29,51,.06)}
.dash{left:16px;top:16px;width:300px}
.dash-h{display:flex;align-items:center;gap:6px;padding:11px 12px 9px 14px;border-bottom:1px solid var(--line-2)}
.dash-h b{font-size:13.5px}
.dash-h .tag{margin-left:auto;font-size:11px;font-weight:700;color:#fff;background:var(--vc);border-radius:999px;padding:2px 9px}
.dash-b{padding:12px 14px 14px}
.rate{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}
.rate .big{font-size:28px;font-weight:800;letter-spacing:-1px}
.rate .of{color:var(--ink-3);font-size:12px}
.bar{height:8px;border-radius:5px;background:#eef2f7;overflow:hidden;display:flex;margin:8px 0 12px}
.bar i{display:block;height:100%}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.kpi{border:1px solid var(--line-2);border-radius:8px;padding:8px 10px;background:#fbfcfe;border-left:3px solid var(--c)}
.kpi span{display:block;font-size:11px;color:var(--ink-3)}
.kpi b{font-size:18px}
.kpi b small{font-size:11px;font-weight:500;color:var(--ink-3);margin-left:2px}
.dash-f{padding:9px 14px;border-top:1px solid var(--line-2);border-radius:0 0 10px 10px;font-size:12px;display:flex;gap:10px;align-items:center}
.dash-f.good{background:#f2f8f3;color:var(--ok)}
.dash-f.badf{background:#fdecec;color:var(--bad)}
.dash-f button{margin-left:auto;border:1px solid currentColor;background:#fff;color:inherit;border-radius:6px;padding:2px 8px;font-size:11px}
.legend{left:16px;bottom:16px;display:flex;gap:12px;align-items:center;padding:8px 14px;font-size:11.5px;color:var(--ink-2);flex-wrap:wrap;max-width:calc(100% - 90px)}
.legend .sw{display:inline-flex;align-items:center;gap:5px}
.legend .grp{color:var(--ink-4);font-size:11px}
.zoom{right:16px;bottom:16px;display:flex;flex-direction:column;padding:3px}
.zoom button{border:0;background:none;width:30px;height:30px;border-radius:6px;font-size:16px;color:var(--ink-2)}
.zoom button:hover{background:#eef2f7}
.zoom .pct{font-size:10px;text-align:center;color:var(--ink-3);padding:2px 0;border-top:1px solid var(--line-2);border-bottom:1px solid var(--line-2)}
.toast{left:50%;bottom:16px;transform:translateX(-50%);padding:8px 14px;font-size:12px;display:none;background:var(--navy);color:#fff;border-color:var(--navy)}
.cable{cursor:pointer}
.cable.dim{opacity:.15}
.node{cursor:pointer}
.node.dim{opacity:.3}
.side{background:var(--paper);border-left:1px solid var(--line);display:flex;flex-direction:column;min-height:0}
.side-h{padding:14px 16px 12px;border-bottom:1px solid var(--line-2)}
.crumb{font-size:11px;color:var(--ink-3)}
.title-row{display:flex;align-items:center;gap:8px;margin-top:6px;flex-wrap:wrap}
.title-row h2{margin:0;font-size:18px;letter-spacing:-.3px;word-break:break-all}
.pill{font-size:11px;font-weight:700;border-radius:999px;padding:2px 9px;color:#fff;background:var(--c)}
.meta{display:grid;grid-template-columns:repeat(3,1fr);margin-top:12px;border:1px solid var(--line-2);border-radius:8px;overflow:hidden}
.meta div{padding:7px 10px;border-right:1px solid var(--line-2);min-width:0}
.meta div:last-child{border-right:0}
.meta span{display:block;font-size:10.5px;color:var(--ink-3)}
.meta b{font-size:13px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.split{display:flex;gap:6px;padding:10px 16px 8px;flex-wrap:wrap;align-items:center;border-bottom:1px solid var(--line-2)}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:3px 9px;font-size:11.5px;color:var(--ink-2);white-space:nowrap}
.chip i{display:inline-block;width:8px;height:8px;border-radius:2px;background:var(--c);margin-right:5px}
.chip.btn{cursor:pointer}
.chip.btn.on{background:var(--navy);color:#fff;border-color:var(--navy)}
.split .r{margin-left:auto}
.mini{border:1px solid var(--line);background:#fff;border-radius:6px;padding:3px 9px;font-size:11.5px;color:var(--ink-2)}
.mini:hover{border-color:var(--accent);color:var(--accent)}
.table-wrap{flex:1;overflow:auto;min-height:0;padding:0 8px 8px}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:12px}
thead th{position:sticky;top:0;background:#f6f8fb;color:var(--ink-3);font-weight:600;font-size:11px;text-align:left;padding:7px 6px;border-bottom:1px solid var(--line);z-index:1}
tbody td{padding:6px;border-bottom:1px solid #f0f3f7;vertical-align:top}
tbody tr:hover td{background:#f7faff}
tbody tr.hit td{background:#fff7d6}
tbody tr.bad td{background:#fdecec}
tbody tr.gone td{color:var(--ink-4)}
td.no{font-family:var(--mono);font-weight:700;color:var(--ink-2);width:30px}
.fc{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
.fc i{width:10px;height:10px;border-radius:50%;border:1px solid rgba(0,0,0,.2);background:var(--c)}
.cid{font-family:var(--mono);font-size:11.5px;word-break:break-all}
.cid s{color:var(--ink-4)}
.arrow{color:var(--xfer);font-weight:800;margin:0 3px}
.sub{display:block;color:var(--ink-3);font-size:11px;font-family:var(--font);margin-top:2px}
.sub.badtxt{color:var(--bad);font-weight:600}
.st{font-size:10.5px;font-weight:700;border-radius:4px;padding:2px 6px;color:#fff;background:var(--c);white-space:nowrap;display:inline-block}
.st.ghost{background:none;color:var(--c);border:1px solid var(--c);padding:1px 5px}
.done{font-size:11px;font-weight:700;white-space:nowrap}
.ph-tag{font-size:10.5px;font-weight:700;color:#7c3aed;border:1px solid #7c3aed;border-radius:4px;padding:0 4px;margin-left:3px;white-space:nowrap;font-family:var(--font)}
.empty{padding:28px 20px;text-align:center;color:var(--ink-3);line-height:1.7}
.list{padding:8px 12px;overflow:auto;flex:1}
.list h4{margin:10px 2px 6px;font-size:12px;color:var(--ink-2);display:flex;align-items:center;gap:6px}
.list h4 .cnt{font-size:11px;color:#fff;background:var(--c);border-radius:999px;padding:0 7px}
.list button{display:flex;width:100%;gap:8px;align-items:flex-start;text-align:left;border:1px solid var(--line-2);background:#fff;border-radius:8px;padding:8px 10px;margin-bottom:6px}
.list button:hover{border-color:var(--accent)}
.list button i{width:4px;align-self:stretch;border-radius:3px;background:var(--c);flex:none}
.list button .t{display:block;font-weight:600}
.list button .d{display:block;color:var(--ink-3);font-size:11.5px;margin-top:2px}
.list .ok{padding:10px 12px;border:1px dashed #b7dfc2;border-radius:8px;color:var(--ok);background:#f4fbf6;font-size:12px;margin-bottom:6px}
.side-f{padding:9px 16px;border-top:1px solid var(--line-2);background:#fbfcfe;font-size:11.5px;color:var(--ink-3)}
tbody tr.editing td{background:#e8f0ff}
.tools{left:50%;transform:translateX(-50%);top:16px;display:flex;gap:4px;align-items:center;padding:5px 6px;border-radius:999px;max-width:calc(100% - 660px);flex-wrap:wrap}
.tools .hint{font-size:11.5px;color:var(--ink-3);padding:0 8px;white-space:nowrap}
.infoform{margin:8px 12px 0;border:1px solid var(--line);border-radius:10px;background:#fbfcfe;padding:8px 12px}
.infoform summary{cursor:pointer;font-weight:700;font-size:12.5px;color:var(--ink-2)}
.infoform summary small{font-weight:500;color:var(--ink-3);margin-left:6px}
.infoform[open] summary{margin-bottom:8px}
.infoform.open{padding-top:12px}
.if-row{display:grid;grid-template-columns:64px 1fr;gap:8px;align-items:center;margin-bottom:7px}
.if-row label{font-size:11.5px;color:var(--ink-3)}
.if-row input,.if-row select{border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:12.5px;background:#fff;min-width:0;width:100%}
.st-group{display:flex;gap:4px;flex-wrap:wrap}
.st-btn{border:1.5px solid var(--c);color:var(--c);background:#fff;border-radius:6px;padding:4px 12px;font-size:12px;font-weight:700}
.st-btn.on{background:var(--c);color:#fff}
.mini.danger{color:var(--bad);border-color:#f3c0c0}
.mini.danger:hover{background:#fdecec}
.editbox{margin:8px 12px;border:1.5px solid var(--accent);border-radius:10px;background:#f8fbff;padding:10px 12px}
.ed-h{display:flex;gap:8px;align-items:baseline;margin-bottom:8px}.ed-h span{color:var(--ink-3);font-size:11.5px}
.ed-row{display:grid;grid-template-columns:52px 1fr 1fr;gap:6px;align-items:center;margin-bottom:6px}
.ed-row small{grid-column:2/-1;color:var(--ink-3);font-size:10.5px;margin-top:-3px}
.ed-l{font-size:11px;font-weight:700;color:#fff;background:var(--c);border-radius:5px;padding:4px 0;text-align:center}
.ed-row input{border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:12.5px;min-width:0;background:#fff}
.ed-row input[data-f="id"]{font-family:var(--mono)}
.ed-row input:focus{outline:2px solid #bcd3fb;border-color:var(--accent)}
.ed-b{display:flex;gap:6px;align-items:center;justify-content:flex-end}
.ed-msg{margin-right:auto;font-size:11.5px;color:var(--ink-3)}.ed-msg.bad{color:var(--bad);font-weight:600}
.ed-note{font-size:12px;color:var(--ink-3);margin-bottom:6px}
.mini.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
footer{background:var(--navy);color:#a9b9d4;font-size:11.5px;display:flex;gap:18px;align-items:center;padding:6px 16px;white-space:nowrap;overflow:hidden}
footer b{color:#fff;font-weight:600}
footer .r{margin-left:auto}
</style>
</head>
<body>
<div class="app" id="app">
  <div class="mode-strip" id="strip"></div>
  <header class="top">
    <div class="brand">
      <svg width="30" height="30" viewBox="0 0 30 30" fill="none" stroke="#9cc0ff" stroke-width="1.8"><circle cx="7" cy="7" r="4"/><circle cx="23" cy="7" r="4"/><circle cx="7" cy="23" r="4"/><circle cx="23" cy="23" r="4"/><path d="M11 7h8M7 11v8M23 11v8M11 23h8"/></svg>
      <div><b>작업도면 · 전·중·후</b><small id="ver"></small></div>
    </div>
    <div class="file"><span class="name" id="fname"></span><span class="when" id="when"></span></div>
    <div class="actions">
      <span class="readonly" id="mode-badge" title="수정은 기존 프로그램 화면에서 합니다">보기 전용</span>
      <button class="btn-top" id="reload" style="display:none" title="프로그램에서 고친 내용을 다시 불러옵니다">새로 고침</button>
      <label class="search"><span style="color:#8ea3c4">⌕</span><input id="q" placeholder="코어ID · 케이블 · 함체 찾기"></label>
      <button class="btn-top" id="copyAll" title="작업전·작업후 배정이 다른 칸을 엑셀에 붙여 넣을 수 있게 복사">절체 목록 복사</button>
      <button class="btn-top" id="fit">전체 보기</button>
    </div>
    <nav class="views" id="views"></nav>
  </header>
  <div class="body">
    <main class="canvas-wrap" id="canvas">
      <svg class="map" id="map"><g id="world"></g></svg>
      <section class="float dash" id="dash"></section>
      <section class="float legend" id="legend"></section>
      <section class="float zoom"><button id="zin" title="확대">＋</button><div class="pct" id="pct">100%</div><button id="zout" title="축소">－</button></section>
      <section class="float toast" id="toast"></section>
      <section class="float tools" id="tools" style="display:none"></section>
    </main>
    <aside class="side" id="side"></aside>
  </div>
  <footer id="foot"></footer>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
let D=JSON.parse(document.getElementById('data').textContent);
const M=D.meta||{};
const VIEWS=[['before','작업전','기설 + 철거 표시','#1565c0'],['during','작업중','기설 · 철거 · 신설 모두','#7c3aed'],['after','작업후','기설 + 신설 (철거 숨김)','#15803d']];
const VISIBLE={before:['기설','철거','절단'],during:['기설','철거','절단','신설'],after:['기설','신설']};
const ROLE_C={'기설':'#1565c0','철거':'#424242','절단':'#d32f2f','신설':'#f59e0b'};
const STATE_C={'유지':'#94a3b8','코어절체':'#7c3aed','해제':'#64748b','신규배정':'#0d9488','신설':'#f59e0b','철거':'#424242','절단':'#d32f2f'};
const STATE_T={'유지':'유지','코어절체':'코어절체','해제':'배정 해제','신규배정':'새로 배정','신설':'신설 배정','철거':'철거','절단':'절단'};
const METHOD_C={'절단절체':'#d32f2f','코어절체':'#2f5fc4'};
const FIBER=[['청','#1e63d6'],['등','#f28c1b'],['녹','#2e9d48'],['갈','#8a5a2b'],['회','#9aa3ad'],['백','#ffffff'],['적','#d62828'],['흑','#222222'],['황','#f5d90a'],['자','#7b3fb5'],['분','#f59ac0'],['옥','#3fc1c9']];
const svgNS='http://www.w3.org/2000/svg';
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function el(t,a,p){const e=document.createElementNS(svgNS,t);for(const k in a)if(a[k]!==undefined&&a[k]!==null)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e}
let nodes,cables,cores,issues,counts,N,C;
function setData(d){D=Object.assign({},D,d);nodes=D.nodes||[];cables=D.cables||[];cores=D.cores||{};issues=D.issues||{};counts=D.counts||{};
  N=Object.fromEntries(nodes.map(n=>[n.id,n]));C=Object.fromEntries(cables.map(c=>[c.id,c]))}
setData({});
const LIVE=!!M.live;let editN=null,busy=false;
let view=(()=>{try{const v=localStorage.getItem('workview.mode');return VISIBLE[v]?v:'during'}catch(e){return 'during'}})();
let sel={kind:null,id:null},query='',hits=new Set(),hitCores=new Set(),focusRows=new Set(),onlyChanged=false;

const shown=c=>VISIBLE[view].includes(c.role);
const nodeShown=n=>view==='during'||(view==='before'?n.role!=='신설':n.role!=='철거');
const cableName=c=>(c.spec||'')+(c.cable_id?' ('+c.cable_id+')':'');
const ends=c=>`${(N[c.a]||{}).name||'?'} ↔ ${(N[c.b]||{}).name||'?'}`;
function idOf(r){return view==='before'?r.b:r.a}
function issueList(v){return v==='before'?(issues.before||[]):v==='after'?(issues.after||[]):[...(issues.before||[]).map(x=>({...x,v:'작업전'})),...(issues.after||[]).map(x=>({...x,v:'작업후'}))]}
function badSlots(){const s=new Set();issueList(view).forEach(i=>(i.n||[]).forEach(n=>s.add(i.cable+'#'+n)));if(view!=='before')(issues.broken||[]).forEach(i=>s.add(i.cable+'#'+i.n[0]));return s}

/* header */
$('ver').textContent='telecom_core · V'+(M.version||'');
if(LIVE){const b=$('mode-badge');b.textContent='수정 가능';b.title='케이블을 누르고 코어 줄을 누르면 코어ID·내역을 고칠 수 있어요. 저장은 바로 프로그램 도면에 됩니다.';b.style.color='#86efac';b.style.borderColor='#2f6b45';$('reload').style.display=''}
$('fname').textContent=M.name||'';
$('when').textContent=M.created?('만든 시각 '+M.created):'';
function renderHeader(){
  const v=VIEWS.find(x=>x[0]===view);document.getElementById('app').style.setProperty('--vc',v[3]);
  $('views').innerHTML=VIEWS.map((x,i)=>`<button class="view${x[0]===view?' on':''}" data-v="${x[0]}" style="--vc:${x[3]}"><span class="n">${i+1}</span>${x[1]} <small>${x[2]}</small></button>`).join('');
  $('views').querySelectorAll('button').forEach(b=>b.onclick=()=>setView(b.dataset.v));
  const note=D.has_after?'현장반영 도면 = 작업전 배정 · 후도면 = 작업후 배정':'후도면이 아직 없어 작업후는 현장반영 배정으로 보여 줍니다';
  $('strip').innerHTML=`<span>●</span>${v[1]} 보기 · ${esc(v[2])}<span class="right">${esc(note)} · ${esc(D.created||M.created||'')} 기준 · ${LIVE?'코어 줄을 눌러 바로 수정':'수정은 기존 프로그램에서'}</span>`;
}
function setView(v){view=v;try{localStorage.setItem('workview.mode',v)}catch(e){}
  if(sel.kind==='cable'&&C[sel.id]&&!shown(C[sel.id]))sel={kind:null,id:null};
  if(sel.kind==='node'&&N[sel.id]&&!nodeShown(N[sel.id]))sel={kind:null,id:null};
  runSearch();renderHeader();renderDash();renderLegend();draw();renderSide();renderFoot();renderTools()}
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT')return;const i=['1','2','3'].indexOf(e.key);if(i>=0)setView(VIEWS[i][0])});

/* drawing */
const world=$('world');
function cableStyle(c){
  const r=c.role;
  if(view==='during'){
    if(r==='철거'||r==='절단')return {color:'#d32f2f',dash:'14 9',w:4,op:.95};
    if(r==='신설')return {color:'#f59e0b',dash:null,w:6,op:1};
    return {color:'#1565c0',dash:null,w:4,op:1};
  }
  if(r==='철거')return {color:'#424242',dash:null,w:4,op:1};
  if(r==='절단')return {color:'#d32f2f',dash:null,w:4,op:1};
  if(r==='신설')return {color:'#f59e0b',dash:null,w:6,op:1};
  return {color:'#1565c0',dash:null,w:4,op:1};
}
function cableBadge(c){
  const rows=cores[c.id]||[];
  if(view==='during'&&c.role==='기설'){const k=rows.filter(r=>r.s==='코어절체').length;return k?['절체 '+k,'#7c3aed']:null}
  if(view==='before'&&(c.role==='철거'||c.role==='절단')){const k=rows.filter(r=>r.b).length;return k?[c.role+' '+k+'코어',ROLE_C[c.role]]:null}
  if(view==='after'&&c.role==='신설'){const k=rows.filter(r=>r.a).length;return ['신설 '+k+'코어','#b45309']}
  return null;
}
function draw(){
  world.innerHTML='';
  const bad=badSlots();
  const gC=el('g',{},world),gL=el('g',{},world),gN=el('g',{},world);
  cables.filter(shown).forEach(c=>{
    const on=sel.kind==='cable'&&sel.id===c.id,st=cableStyle(c);
    const dim=query&&!hits.has('c:'+c.id);
    const g=el('g',{class:'cable'+(dim?' dim':''),'data-id':c.id},gC);
    const hasBad=(cores[c.id]||[]).some(r=>bad.has(c.id+'#'+r.n));
    if(hasBad)el('path',{d:c.d,fill:'none',stroke:'#ff1744','stroke-width':16,'stroke-opacity':.28},g);
    if(on)el('path',{d:c.d,fill:'none',stroke:'#b9f6ca','stroke-width':16},g);
    if(query&&hits.has('c:'+c.id))el('path',{d:c.d,fill:'none',stroke:'#ffd54f','stroke-width':16,'stroke-opacity':.8},g);
    if(view==='during'&&c.role==='신설')el('path',{d:c.d,fill:'none',stroke:'#fff','stroke-width':st.w+4},g);
    el('path',{d:c.d,fill:'none',stroke:on?'#00a843':st.color,'stroke-width':on?st.w+2:st.w,'stroke-dasharray':st.dash,'stroke-opacity':st.op,'stroke-linecap':'round'},g);
    (c.marks||[]).forEach(m=>{
      if(c.role==='철거')el('path',{d:`M ${m[0]-9} ${m[1]-9} L ${m[0]+9} ${m[1]+9} M ${m[0]-9} ${m[1]+9} L ${m[0]+9} ${m[1]-9}`,fill:'none',stroke:view==='during'?'#b71c1c':'#111','stroke-width':3},g);
      else if(c.role==='절단')el('polygon',{points:star(m[0],m[1],12,5.5),fill:'#ff1744',stroke:'#111','stroke-width':2},g);
    });
    el('path',{d:c.d,fill:'none',stroke:'transparent','stroke-width':22},g);
    g.addEventListener('click',e=>{e.stopPropagation();select('cable',c.id)});
    /* label */
    const L=el('g',{class:'cable'+(dim?' dim':'')},gL),[x,y]=c.lab||c.mid;
    const text=cableName(c),w=Math.max(46,text.length*7.2+14);
    el('rect',{x:x-w/2,y:y-11,width:w,height:22,rx:5,fill:'#fff',stroke:on?'#00a843':ROLE_C[c.role],'stroke-width':on?2.5:1.6,'stroke-dasharray':(view==='during'&&(c.role==='철거'||c.role==='절단'))?'4 3':null},L);
    const t=el('text',{x,y,'dominant-baseline':'central','text-anchor':'middle','font-size':11.5,'font-weight':'bold',fill:'#172033','font-family':'var(--font)'},L);t.textContent=text;
    const b=cableBadge(c);
    if(b){const bw=b[0].length*7+14;el('rect',{x:x-bw/2,y:y+13,width:bw,height:17,rx:8.5,fill:b[1]},L);const bt=el('text',{x,y:y+21.5,'dominant-baseline':'central','text-anchor':'middle','font-size':10,'font-weight':'bold',fill:'#fff','font-family':'var(--font)'},L);bt.textContent=b[0]}
    L.addEventListener('click',e=>{e.stopPropagation();select('cable',c.id)});
  });
  nodes.filter(nodeShown).forEach(n=>{
    const on=sel.kind==='node'&&sel.id===n.id,v=n.v||{},x=n.x,y=n.y;
    const dim=query&&!hits.has('n:'+n.id);
    const g=el('g',{class:'node'+(dim?' dim':'')},gN);
    if(on)el('circle',{cx:x,cy:y,r:44,fill:'none',stroke:'#00a843','stroke-width':3,'stroke-dasharray':'6 4'},g);
    if(query&&hits.has('n:'+n.id))el('circle',{cx:x,cy:y,r:46,fill:'#ffd54f','fill-opacity':.45},g);
    if(n.type==='sub'){
      if(n.poly){el('polygon',{points:n.poly,fill:v.fill,stroke:'#fff','stroke-width':12},g);el('polygon',{points:n.poly,fill:v.fill,stroke:v.outline,'stroke-width':3},g)}
      else{el('circle',{cx:x,cy:y,r:27,fill:v.fill,stroke:'#fff','stroke-width':12},g);el('circle',{cx:x,cy:y,r:27,fill:v.fill,stroke:v.outline,'stroke-width':3},g)}
    }else el('circle',{cx:x,cy:y,r:32,fill:v.fill,stroke:v.outline,'stroke-width':3,'stroke-dasharray':(view==='during'&&n.role==='철거')?'7 5':null},g);
    if(v.shape==='circle_x')el('path',{d:`M ${x-22} ${y-22} L ${x+22} ${y+22} M ${x-22} ${y+22} L ${x+22} ${y-22}`,fill:'none',stroke:v.outline,'stroke-width':4},g);
    if(v.symbol_font){const t=el('text',{x,y,'dominant-baseline':'central','text-anchor':'middle','font-family':'Arial','font-size':v.symbol_font,'font-weight':'bold',fill:v.text_fill},g);t.textContent=v.text}
    else if(v.text){const t=el('text',{x,y:y+6,'text-anchor':'middle','font-size':18,'font-weight':'bold',fill:v.text_fill,'font-family':'var(--font)'},g);t.textContent=v.text}
    const name=n.name||'',lw=Math.max(56,Math.min(220,name.length*13+16));
    el('rect',{x:x-lw/2,y:y-61,width:lw,height:24,rx:5,fill:n.name_fill||'#fff',stroke:n.border||'#1565c0','stroke-width':2},g);
    const t=el('text',{x,y:y-49,'dominant-baseline':'central','text-anchor':'middle','font-size':12,'font-weight':'bold',fill:n.name_ink||'#222','font-family':'var(--font)'},g);t.textContent=name;
    if(n.role!=='기설'&&view==='during'){const bw=40;el('rect',{x:x-bw/2,y:y+38,width:bw,height:18,rx:9,fill:ROLE_C[n.role]},g);const bt=el('text',{x,y:y+47,'dominant-baseline':'central','text-anchor':'middle','font-size':10,'font-weight':'bold',fill:'#fff','font-family':'var(--font)'},g);bt.textContent=n.role}
    g.addEventListener('mousedown',e=>{if(!LIVE||tool!=='select'||e.button!==0)return;e.stopPropagation();nodeDrag={id:n.id,sx:e.clientX,sy:e.clientY,moved:false}});
    g.addEventListener('click',e=>{e.stopPropagation();if(justDragged){justDragged=false;return}
      if(LIVE&&tool==='cable')return pickCableEnd(n);select('node',n.id)});
  });
}
function star(cx,cy,o,i){const p=[];for(let k=0;k<10;k++){const r=k%2?i:o,a=-Math.PI/2+k*Math.PI/5;p.push((cx+Math.cos(a)*r).toFixed(1)+','+(cy+Math.sin(a)*r).toFixed(1))}return p.join(' ')}

/* pan & zoom */
const svg=$('map'),B=D.bounds||[0,0,1200,800];
let vb={x:B[0],y:B[1],w:B[2]-B[0],h:B[3]-B[1]},base=1;
function applyView(){svg.setAttribute('viewBox',`${vb.x} ${vb.y} ${vb.w} ${vb.h}`);svg.setAttribute('preserveAspectRatio','xMidYMid meet');$('pct').textContent=Math.round(100*base/vb.w)+'%'}
function fit(){
  const r=svg.getBoundingClientRect(),bw=B[2]-B[0],bh=B[3]-B[1];
  const padL=330,padR=20,padT=30,padB=60,aw=Math.max(200,r.width-padL-padR),ah=Math.max(200,r.height-padT-padB);
  const s=Math.min(aw/bw,ah/bh,1.6);
  vb.w=r.width/s;vb.h=r.height/s;vb.x=B[0]-(padL+(aw-bw*s)/2)/s;vb.y=B[1]-(padT+(ah-bh*s)/2)/s;base=vb.w;applyView();
}
function zoomAt(f,cx,cy){const r=svg.getBoundingClientRect();const px=vb.x+(cx-r.left)/r.width*vb.w,py=vb.y+(cy-r.top)/r.height*vb.h;vb.w*=f;vb.h*=f;vb.x=px-(cx-r.left)/r.width*vb.w;vb.y=py-(cy-r.top)/r.height*vb.h;applyView()}
svg.addEventListener('wheel',e=>{e.preventDefault();zoomAt(e.deltaY>0?1.15:1/1.15,e.clientX,e.clientY)},{passive:false});
let drag=null;
svg.addEventListener('mousedown',e=>{drag={x:e.clientX,y:e.clientY,vx:vb.x,vy:vb.y,moved:false};svg.classList.add('drag')});
window.addEventListener('mousemove',e=>{if(nodeDrag)return moveNodeDrag(e);if(!drag)return;const r=svg.getBoundingClientRect();const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true;vb.x=drag.vx-dx/r.width*vb.w;vb.y=drag.vy-dy/r.height*vb.h;applyView()});
window.addEventListener('mouseup',e=>{if(nodeDrag)return endNodeDrag(e);svg.classList.remove('drag');setTimeout(()=>drag=null,0)});
svg.addEventListener('click',e=>{if(drag&&drag.moved)return;
  if(LIVE&&['hamche','rn','sub'].includes(tool)&&!e.target.closest('.node')){e.stopPropagation();return addNodeAt(e)}
  if(LIVE&&tool==='cable')return;
  select(null,null)},true);
$('zin').onclick=()=>{const r=svg.getBoundingClientRect();zoomAt(1/1.25,r.left+r.width/2,r.top+r.height/2)};
$('zout').onclick=()=>{const r=svg.getBoundingClientRect();zoomAt(1.25,r.left+r.width/2,r.top+r.height/2)};
$('fit').onclick=fit;window.addEventListener('resize',fit);

function select(k,id,rows){
  if(drag&&drag.moved)return;
  if(!(k==='cable'&&sel.kind==='cable'&&sel.id===id))editN=null;
  sel={kind:k,id};focusRows=new Set(rows||[]);draw();renderSide();
}
function focusOn(x,y){vb.x=x-vb.w/2+170*vb.w/svg.getBoundingClientRect().width;vb.y=y-vb.h/2;applyView()}
function goIssue(i){
  const c=C[i.cable];if(!c)return;
  if(!shown(c))setView(c.role==='신설'?'after':'before');
  select('cable',c.id,(i.n||[]).map(n=>c.id+'#'+n));if(c.mid)focusOn(c.mid[0],c.mid[1]);
}

/* dashboard */
function pct(a,b){return b?(Math.round(1000*a/b)/10)+'%':'-'}
function renderDash(){
  const k=counts,st=k.states||{},ro=k.roles||{};let body,foot;
  const iss=issueList(view).length;
  if(view==='before'){
    body=`<div class="rate"><span class="big">${(ro['철거']||0)+(ro['절단']||0)}</span><span class="of">철거·절단 케이블 · 기설 ${ro['기설']||0}개</span></div>
     <div class="kpis" style="margin-top:12px"><div class="kpi" style="--c:#d32f2f"><span>절단절체</span><b>${k.cut||0}<small>코어</small></b></div>
     <div class="kpi" style="--c:#2f5fc4"><span>코어절체</span><b>${k.transfer||0}<small>코어</small></b></div>
     <div class="kpi" style="--c:#424242"><span>철거 칸</span><b>${st['철거']||0}<small>칸</small></b></div>
     <div class="kpi" style="--c:#d32f2f"><span>절단 칸</span><b>${st['절단']||0}<small>칸</small></b></div></div>`;
  }else if(view==='during'){
    const chg=(st['코어절체']||0)+(st['해제']||0)+(st['신규배정']||0);
    body=`<div class="rate"><span class="big">${chg}</span><span class="of">기설에서 번호가 바뀌는 칸 · 유지 ${st['유지']||0}칸</span></div>
     <div class="kpis" style="margin-top:12px"><div class="kpi" style="--c:#7c3aed"><span>코어절체 (전→후 다름)</span><b>${st['코어절체']||0}<small>칸</small></b></div>
     <div class="kpi" style="--c:#0d9488"><span>새로 배정 / 해제</span><b>${st['신규배정']||0}<small>/ ${st['해제']||0}</small></b></div>
     <div class="kpi" style="--c:#d32f2f"><span>철거·절단 칸</span><b>${(st['철거']||0)+(st['절단']||0)}<small>칸</small></b></div>
     <div class="kpi" style="--c:#f59e0b"><span>신설 배정</span><b>${st['신설']||0}<small>칸</small></b></div></div>`;
  }else{
    const t=k.after_total||0,d=k.after_done||0;
    body=`<div class="rate"><span class="big">${pct(d,t)}</span><span class="of">작업후 연결 완료 · ${t}개 중 ${d}개</span></div>
     <div class="bar"><i style="width:${t?100*d/t:0}%;background:var(--ok)"></i><i style="width:${t?100*(t-d)/t:0}%;background:var(--need)"></i></div>
     <div class="kpis"><div class="kpi" style="--c:var(--need)"><span>미완료</span><b>${t-d}<small>코어</small></b></div>
     <div class="kpi" style="--c:#b71c1c"><span>끊긴 코어</span><b>${k.broken||0}<small>코어</small></b></div>
     <div class="kpi" style="--c:#f59e0b"><span>신설 케이블</span><b>${ro['신설']||0}<small>개</small></b></div>
     <div class="kpi" style="--c:#1565c0"><span>기설 유지</span><b>${ro['기설']||0}<small>개</small></b></div></div>`;
  }
  const extra=view==='after'?(k.broken||0):0;
  foot=(iss||extra)?`<div class="dash-f badf">확인 필요 ${iss+extra}건<button id="showIss">목록 보기</button></div>`:`<div class="dash-f good">이 보기 안에서 겹치는 코어 없음</div>`;
  $('dash').innerHTML=`<div class="dash-h"><b>${VIEWS.find(x=>x[0]===view)[1]} 현황</b><span class="tag">${D.has_after?'후도면 기준':'후도면 없음'}</span></div><div class="dash-b">${body}</div>${foot}`;
  const sb=$('showIss');if(sb)sb.onclick=()=>select(null,null);
}

/* legend */
function renderLegend(){
  const line=(c,dash,w)=>`<svg width="28" height="10"><line x1="1" y1="5" x2="27" y2="5" stroke="${c}" stroke-width="${w||4}" stroke-linecap="round"${dash?` stroke-dasharray="${dash}"`:''}/></svg>`;
  const items={before:[['#1565c0',null,'기설'],['#424242',null,'철거 ×'],['#d32f2f',null,'절단 ★']],
    during:[['#1565c0',null,'기설'],['#d32f2f','7 5','철거·절단 (점선)'],['#f59e0b',null,'신설',6]],
    after:[['#1565c0',null,'기설'],['#f59e0b',null,'신설',6]]}[view];
  $('legend').innerHTML='<span class="grp">선</span>'+items.map(x=>`<span class="sw">${line(x[0],x[1],x[3])}${x[2]}</span>`).join('')+
   `<span class="grp">· 칸 상태</span>`+['유지','코어절체','신규배정','해제'].map(s=>`<span class="sw"><span class="st" style="--c:${STATE_C[s]}">${STATE_T[s]}</span></span>`).join('')+
   `<span class="sw" style="color:var(--bad)">■ 빨간 줄 = 이 보기 안의 충돌</span>`;
}

/* side */
function renderSide(){
  if(LIVE&&newCable&&!sel.kind)return renderNewCable();
  if(sel.kind==='cable'&&C[sel.id])return renderCable(C[sel.id]);
  if(sel.kind==='node'&&N[sel.id])return renderNode(N[sel.id]);
  const list=issueList(view),broken=view==='before'?[]:(issues.broken||[]);
  const item=(i,c)=>{const cb=C[i.cable]||{};return `<button data-i="${c}"><i style="--c:${i.kind==='끊김'?'#b71c1c':i.kind==='중복'?'#c62828':'#7b1fa2'}"></i><span><span class="t">${i.v?`[${esc(i.v)}] `:''}${esc(i.id||'(ID 없음)')} · ${esc(cableName(cb))} ${(i.n||[]).join(',')}번</span><span class="d">${esc(i.text)} · ${esc(ends(cb))}</span></span></button>`};
  const all=[...list,...broken];
  $('side').innerHTML=`<div class="side-h"><div class="crumb">작업도면 요약 · ${VIEWS.find(x=>x[0]===view)[1]}</div><div class="title-row"><h2>${esc(M.name||'')}</h2></div>
   <div class="meta"><div><span>기설</span><b>${(counts.roles||{})['기설']||0}</b></div><div><span>철거·절단</span><b>${((counts.roles||{})['철거']||0)+((counts.roles||{})['절단']||0)}</b></div><div><span>신설</span><b>${(counts.roles||{})['신설']||0}</b></div></div></div>
   ${matchList()}
   <div class="list">
    <h4 style="--c:#c62828">이 보기 안의 충돌 <span class="cnt">${list.length}</span></h4>
    ${list.length?list.map((i,k)=>item(i,k)).join(''):`<div class="ok">겹치거나 오류인 코어가 없습니다.</div>`}
    ${view==='before'?'':`<h4 style="--c:#b71c1c">끊긴 코어 (철거됐는데 작업후 경로 없음) <span class="cnt">${broken.length}</span></h4>
    ${broken.length?broken.map((i,k)=>item(i,list.length+k)).join(''):`<div class="ok">철거·절단 코어가 모두 작업후 경로에 있습니다.</div>`}`}
    <div class="empty" style="padding:16px 8px">케이블을 누르면 칸마다 <b>작업전 → 작업후</b> 배정이 나옵니다.<br>숫자키 <b>1·2·3</b>으로 보기를 바꿀 수 있어요.</div>
   </div>`;
  $('side').querySelectorAll('[data-i]').forEach(b=>b.onclick=()=>goIssue(all[+b.dataset.i]));
  bindList($('side'));
}
function matchList(){
  if(!query)return'';
  const cs=cables.filter(c=>shown(c)&&hits.has('c:'+c.id)),ns=nodes.filter(n=>nodeShown(n)&&hits.has('n:'+n.id));
  if(!cs.length&&!ns.length)return `<div class="side-f">「${esc(query)}」 이 보기에서 찾은 결과 없음</div>`;
  return `<div class="list" style="flex:none;max-height:40%"><div class="crumb" style="margin:4px 2px 8px">「${esc(query)}」 찾은 결과 · 케이블 ${cs.length} · 시설 ${ns.length}</div>`+
   cs.map(c=>`<button data-c="${esc(c.id)}"><i style="--c:${ROLE_C[c.role]}"></i><span><span class="t">${esc(cableName(c))}</span><span class="d">${esc(c.role)} · ${esc(ends(c))}</span></span></button>`).join('')+
   ns.map(n=>`<button data-n="${esc(n.id)}"><i style="--c:${n.border||'#1565c0'}"></i><span><span class="t">${esc(n.name)}</span><span class="d">${esc(n.type_label||'')}</span></span></button>`).join('')+'</div>';
}
function bindList(root){
  root.querySelectorAll('[data-c]').forEach(b=>b.onclick=()=>{const c=C[b.dataset.c];select('cable',c.id,[...hitCores].filter(k=>k.startsWith(c.id+'#')));if(c.mid)focusOn(c.mid[0],c.mid[1])});
  root.querySelectorAll('[data-n]').forEach(b=>b.onclick=()=>{const n=N[b.dataset.n];select('node',n.id);focusOn(n.x,n.y)});
}
function doneCell(d,reason){return d===true?'<span class="done" style="color:var(--ok)">완료</span>':d===false?`<span class="done" style="color:var(--bad)" title="${esc(reason)}">미완료</span>`:'<span style="color:#cbd5e1">-</span>'}
function stateTag(s){return s?`<span class="st${s==='유지'?' ghost':''}" style="--c:${STATE_C[s]||'#64748b'}">${esc(STATE_T[s]||s)}</span>`:''}
function idCell(id,det,err){return (id?esc(id):'<span style="color:#cbd5e1">-</span>')+(det?`<span class="sub">${esc(det)}</span>`:'')+(err?`<span class="sub badtxt">${esc(err)}</span>`:'')}
function rowsFor(c){
  let rows=cores[c.id]||[];
  if(view==='during'&&onlyChanged)rows=rows.filter(r=>r.s&&r.s!=='유지');
  return rows;
}
function renderCable(c){
  const all=cores[c.id]||[],rows=rowsFor(c),bad=badSlots();
  const used=all.filter(r=>idOf(r)).length,cnt={};all.forEach(r=>{if(r.s)cnt[r.s]=(cnt[r.s]||0)+1});
  const fiber=n=>{const f=FIBER[(Math.max(1,n)-1)%12];return `<span class="fc"><i style="--c:${f[1]}"></i>${f[0]}</span>`};
  let head,body;
  if(view==='during'){
    head='<th>#</th><th>색</th><th>작업전 → 작업후</th><th>상태</th><th>연결(후)</th>';
    body=rows.map(r=>{const k=c.id+'#'+r.n,same=r.s==='유지';
      const pair=same?esc(r.a):(r.b||r.a)?`${r.b?esc(r.b):'<span style="color:#cbd5e1">빈칸</span>'}<span class="arrow">→</span>${r.a?esc(r.a):(c.role==='철거'||c.role==='절단')?'<s>철거</s>':'<span style="color:#cbd5e1">빈칸</span>'}`:'<span style="color:#cbd5e1">-</span>';
      const err=[r.eb&&('작업전: '+r.eb),r.ea&&('작업후: '+r.ea)].filter(Boolean).join(' / ');
      return `<tr data-row="${r.n}" class="${editN===r.n?'editing':focusRows.has(k)||hitCores.has(k)?'hit':bad.has(k)?'bad':''}"><td class="no">${r.n}</td><td>${fiber(r.n)}</td><td class="cid">${pair}${(r.ph||[]).map(p=>`<span class="ph-tag">${esc(p)}</span>`).join('')}${err?`<span class="sub badtxt">${esc(err)}</span>`:''}</td><td>${stateTag(r.s)}${r.m?`<span class="sub" style="color:${METHOD_C[r.m]}">${esc(r.m)}</span>`:''}</td><td>${doneCell(r.da,r.ra)}</td></tr>`}).join('');
  }else{
    const b=view==='before';
    head=`<th>#</th><th>색</th><th>코어ID · 내역 (${b?'작업전':'작업후'})</th><th>${b?'분배':'상태'}</th><th>연결</th>`;
    body=rows.map(r=>{const k=c.id+'#'+r.n;
      const tag=b?(r.m?`<span class="st" style="--c:${METHOD_C[r.m]}">${esc(r.m)}</span>`:(r.s==='코어절체'?`<span class="st ghost" style="--c:#7c3aed">후: ${esc(r.a||'빈칸')}</span>`:'')):(stateTag(r.s)+(r.s==='코어절체'?`<span class="sub">전: ${esc(r.b)}</span>`:''));
      return `<tr data-row="${r.n}" class="${editN===r.n?'editing':focusRows.has(k)||hitCores.has(k)?'hit':bad.has(k)?'bad':''}"><td class="no">${r.n}</td><td>${fiber(r.n)}</td><td class="cid">${idCell(b?r.b:r.a,b?r.bd:r.ad,b?r.eb:r.ea)}${(r.ph||[]).map(p=>`<span class="ph-tag">${esc(p)}</span>`).join('')}</td><td>${tag}</td><td>${b?doneCell(r.db,r.rb):doneCell(r.da,r.ra)}</td></tr>`}).join('');
  }
  $('side').innerHTML=`<div class="side-h"><div class="crumb">케이블 · ${esc(ends(c))}</div>
   <div class="title-row"><h2>${esc(cableName(c))}</h2><span class="pill" style="--c:${ROLE_C[c.role]}">${esc(c.role)}</span>${(c.phases||[]).map(p=>`<span class="pill" style="--c:#7c3aed">${esc(p)}</span>`).join('')}</div>
   <div class="meta"><div><span>규격</span><b>${esc(c.spec)}</b></div><div><span>LOT</span><b>${esc(c.lot||'-')}</b></div><div><span>사용 코어 (${VIEWS.find(x=>x[0]===view)[1]})</span><b>${used} / ${c.size||all.length}</b></div></div></div>
   <div class="split">${Object.entries(cnt).map(([k,v])=>`<span class="chip"><i style="--c:${STATE_C[k]}"></i>${esc(STATE_T[k]||k)} <b>${v}</b></span>`).join('')}
    ${view==='during'?`<span class="chip btn${onlyChanged?' on':''}" id="onlyChg">바뀐 칸만</span>`:''}<button class="mini r" id="copyOne">표 복사</button></div>
   ${infoForm('cable',c)}
   ${editBox(c)}
   <div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>${rows.length?'':'<div class="empty">보여 줄 칸이 없습니다.</div>'}</div>
   <div class="side-f">${view==='during'?'같은 칸의 작업전·작업후 배정이 다르면 <b>코어절체</b>로 표시합니다 (에러 아님).':'충돌은 이 보기 안에서만 검사합니다 · 미완료에 마우스를 올리면 이유가 보입니다'}${LIVE?' · 코어 줄을 누르면 고칠 수 있어요':''}</div>`;
  const oc=$('onlyChg');if(oc)oc.onclick=()=>{onlyChanged=!onlyChanged;renderCable(c)};
  bindInfo('cable',c);
  if(LIVE){$('side').querySelectorAll('tr[data-row]').forEach(tr=>{tr.style.cursor='pointer';tr.onclick=()=>{editN=+tr.dataset.row;renderCable(c);const f=$('side').querySelector('.editbox input');if(f)f.focus()}});bindEdit(c)}
  $('copyOne').onclick=()=>copyRows([c],'이 케이블 표');
  const first=$('side').querySelector('tr.hit');if(first)first.scrollIntoView({block:'center'});
}
function renderNode(n){
  const list=cables.filter(c=>shown(c)&&(c.a===n.id||c.b===n.id));
  $('side').innerHTML=`<div class="side-h"><div class="crumb">${esc(n.type_label||'시설')}</div>
   <div class="title-row"><h2>${esc(n.name)}</h2><span class="pill" style="--c:${ROLE_C[n.role]||'#1565c0'}">${esc(n.role)}</span></div></div>
   ${infoForm('node',n)}
   <div class="list"><div class="crumb" style="margin:4px 2px 8px">이 보기에서 연결된 케이블 ${list.length}개</div>
   ${list.map(c=>`<button data-c="${esc(c.id)}"><i style="--c:${ROLE_C[c.role]}"></i><span><span class="t">${esc(cableName(c))}</span><span class="d">${esc(c.role)} · ${esc((N[c.a===n.id?c.b:c.a]||{}).name||'')}</span></span></button>`).join('')}</div>`;
  bindInfo('node',n);bindList($('side'));
}

/* V210 drawing tools: move / add facility / add cable / cable and facility info / delete */
let tool='select',nodeDrag=null,justDragged=false,cableStart=null,newCable=null;
const TOOLS=[['select','선택·이동','시설을 끌어서 옮겨요'],['hamche','+ 함체','빈 곳을 누르면 함체를 만들어요'],['rn','+ RN','빈 곳을 누르면 RN을 만들어요'],['sub','+ 가입자','빈 곳을 누르면 가입자를 만들어요'],['cable','+ 케이블','시설 두 개를 차례로 누르세요']];
const target=()=>view==='before'?'before':'after';
const targetName=()=>view==='before'?'현장반영 도면':'후도면';
function renderTools(){
  if(!LIVE)return;const box=$('tools');box.style.display='flex';
  const hint=tool==='cable'&&cableStart?`${esc((N[cableStart]||{}).name||'')} 다음 시설을 누르세요`:esc(TOOLS.find(t=>t[0]===tool)[2]);
  box.innerHTML=TOOLS.map(t=>`<button class="chip btn${t[0]===tool?' on':''}" data-t="${t[0]}">${t[1]}</button>`).join('')+`<span class="hint">${hint} · ${targetName()}에 저장</span>`;
  box.querySelectorAll('button').forEach(b=>b.onclick=()=>{tool=b.dataset.t;cableStart=null;newCable=null;svg.style.cursor=tool==='select'?'':'crosshair';renderTools();if(sel.kind===null)renderSide()});
}
function worldPoint(e){const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;return pt.matrixTransform(world.getScreenCTM().inverse())}
function moveNodeDrag(e){
  if(Math.abs(e.clientX-nodeDrag.sx)+Math.abs(e.clientY-nodeDrag.sy)>4)nodeDrag.moved=true;
  if(!nodeDrag.moved)return;const p=worldPoint(e);let g=$('ghost');
  if(!g){g=el('g',{id:'ghost'},world);el('circle',{r:34,fill:'#2f5fc4','fill-opacity':.18,stroke:'#2f5fc4','stroke-width':3,'stroke-dasharray':'6 4'},g)}
  g.setAttribute('transform',`translate(${p.x},${p.y})`);
}
async function endNodeDrag(e){
  const d=nodeDrag;nodeDrag=null;const g=$('ghost');if(g)g.remove();
  if(!d.moved)return;justDragged=true;setTimeout(()=>justDragged=false,300);
  const p=worldPoint(e);await edit('node_move',{node:d.id,x:p.x,y:p.y},'시설을 옮겼어요');
}
async function addNodeAt(e){
  const p=worldPoint(e),label={hamche:'함체',rn:'RN',sub:'가입자'}[tool];
  const name=(window.prompt(`새 ${label} 이름 (${targetName()}에 만들어요)`,'')||'').trim();if(!name)return;
  const res=await edit('node_add',{name,type:tool,x:p.x,y:p.y},`${label} 「${name}」을 만들었어요`);
  if(res&&res.ok){tool='select';svg.style.cursor='';renderTools();select('node',res.result)}
}
function pickCableEnd(n){
  if(!cableStart){cableStart=n.id;renderTools();return}
  if(cableStart===n.id){cableStart=null;renderTools();return}
  newCable={a:cableStart,b:n.id};cableStart=null;renderTools();sel={kind:null,id:null};draw();renderNewCable();
}
function sizeOptions(cur){const list=(M.sizes||[]).slice();if(cur&&!list.includes(cur))list.unshift(cur);return list.map(x=>`<option${x===cur?' selected':''}>${esc(x)}</option>`).join('')}
function statusButtons(cur){return (M.statuses||['기설','신설','철거','절단']).map(x=>`<button type="button" class="st-btn${x===cur?' on':''}" data-st="${esc(x)}" style="--c:${ROLE_C[x]}">${esc(x)}</button>`).join('')}
function renderNewCable(){
  const a=N[newCable.a]||{},b=N[newCable.b]||{},st=view==='before'?'기설':'신설';
  $('side').innerHTML=`<div class="side-h"><div class="crumb">새 케이블 · ${targetName()}에 만들어요</div><div class="title-row"><h2>${esc(a.name)} ↔ ${esc(b.name)}</h2></div></div>
   <div class="infoform open"><div class="if-row"><label>상태</label><div class="st-group">${statusButtons(st)}</div></div>
   <div class="if-row"><label>규격</label><select id="ncSpec">${sizeOptions('12C')}</select></div>
   <div class="if-row"><label>케이블 ID</label><input id="ncId" placeholder="${st==='신설'?'비우면 NEW 번호 자동':'예: 광주-101'}"></div>
   <div class="if-row"><label>LOT</label><input id="ncLot" placeholder="LOT NO."></div>
   <div class="ed-b"><span class="ed-msg" id="ncMsg"></span><button class="mini" id="ncCancel">취소</button><button class="mini primary" id="ncSave">케이블 만들기</button></div></div>`;
  let status=st;$('side').querySelectorAll('.st-btn').forEach(b=>b.onclick=()=>{status=b.dataset.st;$('side').querySelectorAll('.st-btn').forEach(x=>x.classList.toggle('on',x===b))});
  $('ncCancel').onclick=()=>{newCable=null;renderSide()};
  $('ncSave').onclick=async()=>{const res=await edit('cable_add',{a:newCable.a,b:newCable.b,status,spec:$('ncSpec').value,cable_id:$('ncId').value,lot:$('ncLot').value},'케이블을 만들었어요',$('ncMsg'));
    if(res&&res.ok){newCable=null;tool='select';svg.style.cursor='';renderTools();if(C[res.result]&&shown(C[res.result]))select('cable',res.result);else renderSide()}};
}
function infoForm(kind,x){
  if(!LIVE)return'';const v=(x.edit||{})[target()];
  if(!v)return `<div class="infoform"><div class="ed-note">이 ${kind==='cable'?'케이블':'시설'}은 ${targetName()}에 없어요. ${target()==='after'?'작업전':'작업후'} 보기에서 고치세요.</div></div>`;
  const rows=kind==='cable'?`<div class="if-row"><label>상태</label><div class="st-group">${statusButtons(v.status)}</div></div>
     <div class="if-row"><label>규격</label><select data-k="spec">${sizeOptions(v.spec)}</select></div>
     <div class="if-row"><label>케이블 ID</label><input data-k="cable_id" value="${esc(v.cable_id)}"></div>
     <div class="if-row"><label>LOT</label><input data-k="lot" value="${esc(v.lot)}"></div>`:
    `<div class="if-row"><label>이름</label><input data-k="name" value="${esc(v.name)}"></div>
     <div class="if-row"><label>상태</label><div class="st-group">${statusButtons(v.status)}</div></div>`;
  return `<details class="infoform"${infoOpen?' open':''}><summary>${kind==='cable'?'케이블':'시설'} 정보 고치기 <small>${targetName()}에 저장</small></summary>${rows}
    <div class="ed-b"><button class="mini danger" data-del="1">${kind==='cable'?'케이블':'시설'} 삭제</button><span class="ed-msg" data-msg="1"></span><button class="mini primary" data-save="1">저장</button></div></details>`;
}
let infoOpen=false;
function bindInfo(kind,x){
  if(!LIVE)return;const box=$('side').querySelector('.infoform');if(!box||!box.querySelector('[data-save]'))return;
  box.addEventListener('toggle',()=>{infoOpen=box.open});
  const v=x.edit[target()];let status=v.status;
  box.querySelectorAll('.st-btn').forEach(b=>b.onclick=()=>{status=b.dataset.st;box.querySelectorAll('.st-btn').forEach(y=>y.classList.toggle('on',y===b))});
  const val=k=>{const i=box.querySelector(`[data-k="${k}"]`);return i?i.value.trim():''};
  const msg=box.querySelector('[data-msg]');
  box.querySelector('[data-save]').onclick=async()=>{
    if(kind==='cable'){
      const ns=parseInt(val('spec'))||1,os=parseInt(v.spec)||1;
      if(ns<os&&!window.confirm(`${v.spec}에서 ${val('spec')}로 줄이면 ${ns+1}번 이후 코어와 연결이 지워져요. 계속할까요?`))return;
      await edit('cable_info',{cable:x.id,status,spec:val('spec'),cable_id:val('cable_id'),lot:val('lot')},'케이블 정보를 저장했어요',msg);
    }else await edit('node_info',{node:x.id,name:val('name'),status},'시설 정보를 저장했어요',msg);
  };
  box.querySelector('[data-del]').onclick=async()=>{
    const what=kind==='cable'?`케이블 ${cableName(x)}`:`시설 ${x.name} (연결된 케이블도 함께)`;
    if(!window.confirm(`${targetName()}에서 ${what}을 지울까요? 프로그램에서 실행취소(Ctrl+Z)로 되돌릴 수 있어요.`))return;
    const res=await edit('delete',{kind,id:x.id},'지웠어요',msg);if(res&&res.ok){sel={kind:null,id:null};renderAll()}
  };
}
async function edit(op,body,done,msgEl){
  if(busy)return null;busy=true;if(msgEl){msgEl.textContent='저장 중…';msgEl.className='ed-msg'}
  try{
    const res=await api('edit',Object.assign({op,view},body));
    if(!res.ok){const t=res.error||'저장하지 못했어요';if(msgEl){msgEl.textContent=t;msgEl.className='ed-msg bad'}else toast(t);return res}
    applyScene(res.scene);if(sel.kind==='cable'&&!C[sel.id]||sel.kind==='node'&&!N[sel.id])sel={kind:null,id:null};
    renderAll();toast(done+' · '+res.where+' 저장');return res;
  }catch(e){toast('프로그램과 연결이 끊겼어요. 프로그램이 켜져 있는지 확인하세요.');return null}
  finally{busy=false}
}

/* V209 editing (only when opened from the program) */
function editSides(c){
  const out=[];
  if(c.in_before&&(view==='before'||view==='during'))out.push(['before','작업전','현장반영 도면에 저장','b','bd']);
  if(D.has_after&&c.in_after&&(view==='after'||view==='during'))out.push(['after','작업후','후도면에 저장','a','ad']);
  return out;
}
function editBox(c){
  if(!LIVE||editN==null)return '';
  const r=(cores[c.id]||[]).find(x=>x.n===editN);if(!r)return '';
  const sides=editSides(c);
  const body=sides.length?sides.map(s=>`<div class="ed-row"><span class="ed-l" style="--c:${s[0]==='before'?'#1565c0':'#15803d'}">${s[1]}</span>
     <input data-side="${s[0]}" data-f="id" value="${esc(r[s[3]])}" placeholder="코어ID (비우면 배정 해제)">
     <input data-side="${s[0]}" data-f="detail" value="${esc(r[s[4]])}" placeholder="내역"><small>${s[2]}</small></div>`).join(''):
     '<div class="ed-note">이 보기에서는 이 케이블을 고칠 수 없어요. 작업전·작업중·작업후 중 이 케이블이 있는 보기로 바꾸세요.</div>';
  return `<div class="editbox"><div class="ed-h"><b>${editN}번 코어 고치기</b><span>${esc(cableName(c))}</span></div>${body}
    <div class="ed-b"><span class="ed-msg" id="edMsg"></span><button class="mini" id="edCancel">닫기</button>${sides.length?'<button class="mini primary" id="edSave">저장 (Enter)</button>':''}</div></div>`;
}
function bindEdit(c){
  const save=$('edSave'),cancel=$('edCancel');
  if(cancel)cancel.onclick=()=>{editN=null;renderCable(c)};
  if(!save)return;
  const box=$('side').querySelector('.editbox');
  box.querySelectorAll('input').forEach(i=>i.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();save.click()}if(e.key==='Escape'){editN=null;renderCable(c)}}));
  save.onclick=async()=>{
    if(busy)return;
    const r=(cores[c.id]||[]).find(x=>x.n===editN);const jobs=[];
    editSides(c).forEach(s=>{const id=box.querySelector(`input[data-side="${s[0]}"][data-f="id"]`).value.trim(),det=box.querySelector(`input[data-side="${s[0]}"][data-f="detail"]`).value.trim();
      if(id!==(r[s[3]]||'')||det!==(r[s[4]]||''))jobs.push({view:s[0],cable:c.id,n:editN,id,detail:det,label:s[1]})});
    if(!jobs.length){$('edMsg').textContent='바뀐 내용이 없어요.';return}
    busy=true;save.disabled=true;$('edMsg').textContent='저장 중…';
    try{
      for(const j of jobs){
        const res=await api('core',j);
        if(!res.ok){$('edMsg').textContent=j.label+': '+(res.error||'저장하지 못했어요');$('edMsg').className='ed-msg bad';return}
        applyScene(res.scene);
      }
      toast(jobs.map(j=>j.label).join('·')+' '+editN+'번 저장됨');const next=editN+1;
      editN=(cores[c.id]||[]).some(x=>x.n===next)?next:null;renderAll();
      const f=$('side').querySelector('.editbox input');if(f)f.focus();
    }catch(e){$('edMsg').textContent='프로그램과 연결이 끊겼어요. 프로그램이 켜져 있는지 확인하고 다시 여세요.';$('edMsg').className='ed-msg bad'}
    finally{busy=false;if(save)save.disabled=false}
  };
}
async function api(name,body){
  const res=await fetch(body===undefined?'/api/'+name:'/api/'+name,{method:body===undefined?'GET':'POST',headers:{'X-Telecom-Token':M.token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
  return res.json();
}
function applyScene(scene){if(scene)setData(scene)}
function renderAll(){runSearch();renderHeader();renderDash();renderLegend();draw();renderSide();renderFoot();renderTools()}
async function reload(){if(!LIVE||busy)return;try{const res=await api('scene');if(res.ok){applyScene(res.value);renderAll();toast('프로그램 도면을 다시 불러왔어요')}else toast(res.error||'불러오지 못했어요')}catch(e){toast('프로그램과 연결이 끊겼어요')}}
if(LIVE)$('reload').onclick=reload;

/* copy for Excel */
function toast(t){const e=$('toast');e.textContent=t;e.style.display='block';clearTimeout(toast.h);toast.h=setTimeout(()=>e.style.display='none',2200)}
function clip(text,label){
  const done=()=>toast(label+' 복사됨 · 엑셀에 붙여 넣으세요');
  const fallback=()=>{const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();try{document.execCommand('copy');done()}catch(e){toast('복사하지 못했습니다')}ta.remove()};
  if(navigator.clipboard&&window.isSecureContext)navigator.clipboard.writeText(text).then(done,fallback);else fallback();
}
function copyRows(list,label,filter){
  const out=[['케이블','규격','구간','케이블 상태','번호','작업전 코어ID','작업후 코어ID','칸 상태','분배','작업후 연결'].join('\t')];
  list.forEach(c=>(cores[c.id]||[]).forEach(r=>{
    if(filter&&!filter(r,c))return;
    out.push([c.cable_id||c.id,c.spec,ends(c),c.role,r.n,r.b,r.a,STATE_T[r.s]||r.s,r.m,r.da===true?'완료':r.da===false?'미완료':''].map(v=>String(v==null?'':v).replace(/[\t\n]/g,' ')).join('\t'));
  }));
  clip(out.join('\n'),label);
}
$('copyAll').onclick=()=>copyRows(cables,'절체 목록',(r,c)=>['코어절체','해제','신규배정'].includes(r.s)||!!r.m);

/* search */
function runSearch(){
  hits=new Set();hitCores=new Set();
  if(!query)return;
  const q=query.toLowerCase();
  for(const c of cables){
    if(!shown(c))continue;
    if(cableName(c).toLowerCase().includes(q)||(c.lot||'').toLowerCase().includes(q))hits.add('c:'+c.id);
    for(const r of cores[c.id]||[]){
      const ids=view==='during'?[r.b,r.a]:[idOf(r)];
      if(ids.some(x=>x&&x.toLowerCase().includes(q))){hits.add('c:'+c.id);hitCores.add(c.id+'#'+r.n);hits.add('n:'+c.a);hits.add('n:'+c.b)}
    }
  }
  for(const n of nodes)if(nodeShown(n)&&(n.name||'').toLowerCase().includes(q))hits.add('n:'+n.id);
}
$('q').addEventListener('input',e=>{query=e.target.value.trim();runSearch();draw();renderSide()});

function renderFoot(){
  const vis=cables.filter(shown),ro={};vis.forEach(c=>ro[c.role]=(ro[c.role]||0)+1);
  $('foot').innerHTML=`<span>보기 <b>${VIEWS.find(x=>x[0]===view)[1]}</b></span><span>케이블 <b>${vis.length}</b> (${Object.entries(ro).map(([k,v])=>esc(k)+' '+v).join(' · ')})</span><span>시설 <b>${nodes.filter(nodeShown).length}</b></span><span class="r">통신 코어 도면 V${esc(M.version||'')} · ${LIVE?'프로그램과 연결됨 · 수정 가능':'보기 전용'}</span>`;
}

renderHeader();renderDash();renderLegend();renderFoot();draw();renderSide();renderTools();fit();
</script>
</body>
</html>
'''
