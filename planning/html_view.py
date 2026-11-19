"""V207: open the current drawing in the new HTML screen (read-only view).

The desktop app keeps every calculation and all editing. This module only turns
what the app already computed (drawing geometry, cable/core rows, work method,
completion) into one self-contained HTML file that a browser opens offline:

- html_view_cores(store, work, report) -> {cable row id: [core rows]}
- html_view_dashboard(store, work) -> numbers of the 작업코어 현황 card
- html_view_document(scene, meta) -> the whole HTML text (no network needed)

Nothing here writes to the drawing database.
"""


HTML_VIEW_STAGES=(('gis','임시도면'),('before','현장반영'),('check','완성도 점검'),('after','후도면'),('complete','후도면 작업실'))
HTML_VIEW_FILE='도면_HTML화면.html'


def _html_view_slot(slot):
    try:return (str(slot[0]),int(slot[1]))
    except (TypeError,ValueError,IndexError):return None


def html_view_methods(work):
    """{(cable id, core number): '절단절체' | '코어절체'} from the work list rows."""
    methods={}
    for row in (work or {}).get('rows') or ():
        method=str(row.get('method') or '')
        if not method:continue
        for field in ('source_slots','current_slots'):
            for slot in row.get(field) or ():
                key=_html_view_slot(slot)
                if key:methods.setdefault(key,method)
    return methods


def html_view_cores(store,work=None,report=None):
    """Core rows per cable for the side table. Every lookup is best-effort so a
    failing helper only leaves a column empty instead of blocking the view."""
    methods=html_view_methods(work)
    by_slot=(report or {}).get('by_slot') or {}
    result={}
    for cable in store.cables():
        rows=[]
        try:cores=store.cores(cable['id'])
        except Exception:cores=[]
        for core in cores:
            core=dict(core);number=int(core.get('core_index') or 0);cid=str(core.get('core_id') or '').strip()
            try:phases=[work_phase_short(n) for n in phase_names(store,core)]
            except Exception:phases=[]
            entry=by_slot.get((cable['id'],number))
            if entry is None:done=None;reason=''
            elif not entry.get('required',True):done=None;reason=str(entry.get('excluded_reason') or '')
            else:done=bool(entry.get('complete'));reason='' if done else str(entry.get('reason') or '')
            rows.append(dict(n=number,id=cid,detail=str(core.get('detail') or ''),
                             labels=[str(x) for x in core.get('annotation_labels') or ()],
                             signal=str(core.get('signal') or ''),phases=phases,
                             method=methods.get((str(cable['id']),number),''),done=done,reason=reason[:300]))
        result[str(cable['id'])]=rows
    return result


def html_view_dashboard(store,work=None):
    value=dict(kind='',all=0,total=0,done=0,rate=None,cut=0,transfer=0,errors=0,
               drawing_total=0,drawing_done=0,drawing_rate=None,note='')
    try:
        report=work_core_list_report(store,work or {})
        value.update(kind=report['kind'],all=report['all'],total=report['total'],done=report['done'],rate=report['rate'],
                     cut=report['cut'],transfer=report['transfer'])
        if report['kind']=='gis':value['note']='임시도면은 작업코어 판정 제외'
        elif report.get('missing_before'):value['note']='저장된 현장반영 도면 없음'
        elif not report['all']:value['note']='절단·철거 표시된 케이블·함체·RN 없음'
    except Exception:value['note']='작업코어 계산을 불러오지 못했습니다'
    try:
        overall=store.drawing_connection_progress()
        value.update(drawing_total=overall['total'],drawing_done=overall['done'],drawing_rate=overall['rate'])
    except Exception:pass
    try:value['errors']=int(store.error_core_summary()['core_count'])
    except Exception:pass
    return value


def html_view_json(value):
    """JSON that is safe inside a <script> block."""
    text=json.dumps(value,ensure_ascii=False,separators=(',',':'),default=str)
    return text.replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026').replace('\u2028','\\u2028').replace('\u2029','\\u2029')


def html_view_document(scene,meta):
    import html as _html
    data=dict(scene,meta=meta)
    title=_html.escape('통신 코어 도면 · '+str(meta.get('name') or ''))
    return HTML_VIEW_TEMPLATE.replace('__TITLE__',title).replace('__DATA__',html_view_json(data))


HTML_VIEW_TEMPLATE=r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --navy:#101d33;--navy-3:#22375a;--line:#dbe3ed;--line-2:#e8eef5;--bg:#f3f6fa;--paper:#fff;
  --ink:#172033;--ink-2:#475569;--ink-3:#64748b;--ink-4:#94a3b8;--accent:#2f5fc4;--accent-soft:#edf3fc;
  --ok:#15803d;--bad:#c62828;--need:#ff1744;--stage:#315eac;
  --font:"Malgun Gothic","맑은 고딕","Pretendard","Noto Sans KR","Noto Sans CJK KR",system-ui,sans-serif;
  --mono:"D2Coding","Consolas","Noto Sans Mono",ui-monospace,monospace;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{font-family:var(--font);color:var(--ink);background:var(--bg);font-size:13px;overflow:hidden}
button,input{font:inherit;color:inherit}
button{cursor:pointer}
.app{display:grid;grid-template-rows:auto auto 1fr auto;height:100vh}
.mode-strip{background:var(--stage);color:#fff;font-weight:700;font-size:12px;padding:5px 16px;display:flex;gap:10px;align-items:center}
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
.search input{background:none;border:0;outline:0;color:#fff;padding:7px 4px;width:190px;font-size:12px}
.search input::placeholder{color:#8ea3c4}
.btn-top{background:var(--navy-3);border:1px solid #2f4a74;color:#e6eefb;border-radius:6px;padding:7px 12px;font-size:12px}
.btn-top:hover{background:#2b4570}
.readonly{font-size:11px;font-weight:700;color:#ffd166;border:1px solid #6b5a2a;border-radius:999px;padding:4px 10px;white-space:nowrap}
.stages{grid-column:1/-1;display:flex;margin:0 -16px;padding:0 16px;border-top:1px solid #1d2f4f}
.stage{flex:1;display:flex;align-items:center;gap:8px;justify-content:center;padding:9px 6px 10px;color:#8ea3c4;font-size:12.5px;position:relative;white-space:nowrap}
.stage .n{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;font-size:11px;font-weight:700;border:1.5px solid #3a5582}
.stage.on{color:#fff;font-weight:700;background:rgba(255,255,255,.06)}
.stage.on .n{background:var(--stage);border-color:var(--stage);color:#fff}
.stage.on::after{content:"";position:absolute;left:10%;right:10%;bottom:0;height:3px;border-radius:3px 3px 0 0;background:#7fb0ff}
.body{display:grid;grid-template-columns:1fr 400px;min-height:0}
.canvas-wrap{position:relative;min-width:0;overflow:hidden;background:radial-gradient(circle at 1px 1px,#d5dde8 1px,transparent 1.2px) 0 0/24px 24px,#f7f9fc}
svg.map{position:absolute;inset:0;width:100%;height:100%;cursor:grab;user-select:none}
svg.map.drag{cursor:grabbing}
.float{position:absolute;background:var(--paper);border:1px solid var(--line);border-radius:10px;box-shadow:0 6px 24px rgba(16,29,51,.08),0 1px 2px rgba(16,29,51,.06)}
.dash{left:16px;top:16px;width:290px}
.dash-h{display:flex;align-items:center;gap:6px;padding:11px 12px 9px 14px;border-bottom:1px solid var(--line-2)}
.dash-h b{font-size:13.5px}
.seg{margin-left:auto;display:flex;background:#eef2f7;border-radius:6px;padding:2px}
.seg button{border:0;background:none;font-size:11px;padding:3px 8px;border-radius:5px;color:var(--ink-3)}
.seg button.on{background:#fff;color:var(--accent);font-weight:700;box-shadow:0 1px 2px rgba(0,0,0,.08)}
.icon-btn{border:0;background:none;color:var(--ink-3);border-radius:5px;padding:3px 5px;font-size:11px}
.icon-btn:hover{background:#eef2f7}
.dash-b{padding:12px 14px 14px}
.dash.closed .dash-b{display:none}
.rate{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}
.rate .big{font-size:30px;font-weight:800;letter-spacing:-1px}
.rate .of{color:var(--ink-3);font-size:12px}
.bar{height:8px;border-radius:5px;background:#eef2f7;overflow:hidden;display:flex;margin:8px 0 12px}
.bar i{display:block;height:100%}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.kpi{border:1px solid var(--line-2);border-radius:8px;padding:8px 10px;background:#fbfcfe;border-left:3px solid var(--c)}
.kpi span{display:block;font-size:11px;color:var(--ink-3)}
.kpi b{font-size:18px}
.kpi b small{font-size:11px;font-weight:500;color:var(--ink-3);margin-left:2px}
.dash-note{font-size:12px;color:var(--ink-3);margin-top:4px}
.dash-f{padding:9px 14px;border-top:1px solid var(--line-2);border-radius:0 0 10px 10px;font-size:12px}
.dash-f.good{background:#f2f8f3;color:var(--ok)}
.dash-f.badf{background:#f3e5f5;color:#7b1fa2}
.phasebar{left:50%;transform:translateX(-50%);top:16px;display:flex;align-items:center;gap:4px;padding:5px;border-radius:999px;max-width:calc(100% - 640px);overflow-x:auto}
.phasebar span.t{font-size:11.5px;color:var(--ink-3);padding:0 6px 0 10px;white-space:nowrap}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:4px 11px;font-size:12px;color:var(--ink-2);white-space:nowrap}
.chip.on{background:var(--navy);color:#fff;border-color:var(--navy)}
.chip .cnt{font-size:10.5px;opacity:.7;margin-left:3px}
.legend{left:16px;bottom:16px;display:flex;gap:12px;align-items:center;padding:8px 14px;font-size:11.5px;color:var(--ink-2);flex-wrap:wrap;max-width:calc(100% - 90px)}
.legend .sw{display:inline-flex;align-items:center;gap:5px}
.legend .grp{color:var(--ink-4);font-size:11px}
.zoom{right:16px;bottom:16px;display:flex;flex-direction:column;padding:3px}
.zoom button{border:0;background:none;width:30px;height:30px;border-radius:6px;font-size:16px;color:var(--ink-2)}
.zoom button:hover{background:#eef2f7}
.zoom .pct{font-size:10px;text-align:center;color:var(--ink-3);padding:2px 0;border-top:1px solid var(--line-2);border-bottom:1px solid var(--line-2)}
.toast{left:50%;bottom:16px;transform:translateX(-50%);padding:8px 14px;font-size:12px;display:none}
.cable{cursor:pointer}
.cable.dim,.lbl.dim{opacity:.15}
.node{cursor:pointer}
.node.dim{opacity:.35}
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
.split{display:flex;gap:6px;padding:10px 16px 8px;flex-wrap:wrap;border-bottom:1px solid var(--line-2)}
.split .chip{font-size:11.5px;padding:3px 9px}
.split .chip i{display:inline-block;width:8px;height:8px;border-radius:2px;background:var(--c);margin-right:5px}
.table-wrap{flex:1;overflow:auto;min-height:0;padding:0 8px 8px}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:12px}
thead th{position:sticky;top:0;background:#f6f8fb;color:var(--ink-3);font-weight:600;font-size:11px;text-align:left;padding:7px 6px;border-bottom:1px solid var(--line);z-index:1}
tbody td{padding:6px;border-bottom:1px solid #f0f3f7;vertical-align:top}
tbody tr:hover td{background:#f7faff}
tbody tr.hit td{background:#fff7d6}
td.no{font-family:var(--mono);font-weight:700;color:var(--ink-2);width:30px}
.fc{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
.fc i{width:10px;height:10px;border-radius:50%;border:1px solid rgba(0,0,0,.2);background:var(--c)}
.cid{font-family:var(--mono);font-size:11.5px;word-break:break-all}
.sub{display:block;color:var(--ink-3);font-size:11px;font-family:var(--font);margin-top:2px}
.st{font-size:10.5px;font-weight:700;border-radius:4px;padding:2px 6px;color:#fff;background:var(--c);white-space:nowrap;display:inline-block}
.done{font-size:11px;font-weight:700;white-space:nowrap}
.ph-tag{font-size:10.5px;font-weight:700;color:var(--c);border:1px solid var(--c);border-radius:4px;padding:0 5px;margin-right:2px;white-space:nowrap}
.empty{padding:40px 20px;text-align:center;color:var(--ink-3);line-height:1.7}
.list{padding:8px 12px;overflow:auto;flex:1}
.list button{display:flex;width:100%;gap:8px;align-items:center;text-align:left;border:1px solid var(--line-2);background:#fff;border-radius:8px;padding:8px 10px;margin-bottom:6px}
.list button:hover{border-color:var(--accent)}
.list i{width:22px;height:5px;border-radius:3px;background:var(--c);flex:none}
.list .r{margin-left:auto;color:var(--ink-3);font-size:11px;white-space:nowrap}
.side-f{padding:9px 16px;border-top:1px solid var(--line-2);background:#fbfcfe;font-size:11.5px;color:var(--ink-3)}
footer{background:var(--navy);color:#a9b9d4;font-size:11.5px;display:flex;gap:18px;align-items:center;padding:6px 16px;white-space:nowrap;overflow:hidden}
footer b{color:#fff;font-weight:600}
footer .r{margin-left:auto}
</style>
</head>
<body>
<div class="app">
  <div class="mode-strip" id="strip"></div>
  <header class="top">
    <div class="brand">
      <svg width="30" height="30" viewBox="0 0 30 30" fill="none" stroke="#9cc0ff" stroke-width="1.8"><circle cx="7" cy="7" r="4"/><circle cx="23" cy="7" r="4"/><circle cx="7" cy="23" r="4"/><circle cx="23" cy="23" r="4"/><path d="M10 10l10 10M20 10L10 20"/></svg>
      <div><b>통신 코어 도면</b><small id="ver"></small></div>
    </div>
    <div class="file"><span class="name" id="fname"></span><span class="when" id="when"></span></div>
    <div class="actions">
      <span class="readonly" title="수정은 기존 프로그램 화면에서 합니다">보기 전용</span>
      <label class="search"><span style="color:#8ea3c4">⌕</span><input id="q" placeholder="코어ID · 케이블 · 함체 찾기"></label>
      <button class="btn-top" id="fit">전체 보기</button>
    </div>
    <nav class="stages" id="stages"></nav>
  </header>
  <div class="body">
    <main class="canvas-wrap" id="canvas">
      <svg class="map" id="map"><g id="world"></g></svg>
      <section class="float dash" id="dash"></section>
      <section class="float phasebar" id="phasebar"></section>
      <section class="float legend" id="legend"></section>
      <section class="float zoom"><button id="zin" title="확대">＋</button><div class="pct" id="pct">100%</div><button id="zout" title="축소">－</button></section>
      <section class="float toast" id="toast"></section>
    </main>
    <aside class="side" id="side"></aside>
  </div>
  <footer id="foot"></footer>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const D=JSON.parse(document.getElementById('data').textContent);
const M=D.meta||{};
const STATUS_C={'기설':'#1565c0','신설':'#f9a825','철거':'#424242','절단':'#d32f2f'};
const PHASE_P=['#7c3aed','#0d9488','#db2777','#ea580c','#0284c7','#65a30d','#9333ea','#b45309'];
const FIBER=[['청','#1e63d6'],['등','#f28c1b'],['녹','#2e9d48'],['갈','#8a5a2b'],['회','#9aa3ad'],['백','#ffffff'],['적','#d62828'],['흑','#222222'],['황','#f5d90a'],['자','#7b3fb5'],['분','#f59ac0'],['옥','#3cc7c9']];
const METHOD_C={'절단절체':'#d32f2f','코어절체':'#2f5fc4'};
const svgNS='http://www.w3.org/2000/svg';
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function el(t,a,p){const e=document.createElementNS(svgNS,t);for(const k in a)if(a[k]!==undefined&&a[k]!==null)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e}
const nodes=D.nodes||[],cables=D.cables||[],labels=D.labels||[],cores=D.cores||{},details=D.details||[];
const N=Object.fromEntries(nodes.map(n=>[n.id,n])),C=Object.fromEntries(cables.map(c=>[c.id,c]));
const phaseNames=[];cables.forEach(c=>(c.phases||[]).forEach(p=>{if(!phaseNames.includes(p))phaseNames.push(p)}));
Object.values(cores).forEach(rows=>rows.forEach(r=>(r.phases||[]).forEach(p=>{if(!phaseNames.includes(p))phaseNames.push(p)})));
const PC=p=>PHASE_P[Math.max(0,phaseNames.indexOf(p))%PHASE_P.length];
let sel={kind:null,id:null},phase='전체',query='',hits=new Set(),hitCores=new Set();

/* header */
const kind=M.kind||'before',stageLabel=M.stage_label||'';
$('strip').innerHTML=`<span>●</span>${esc(stageLabel)} 도면 · HTML 보기 전용<span class="right">${esc(M.created||'')} 기준 · 수정은 기존 프로그램에서 하고 이 화면은 다시 열면 새로 반영됩니다</span>`;
$('ver').textContent='telecom_core · V'+(M.version||'');
$('fname').textContent=M.name||'';
$('when').textContent=M.created?('만든 시각 '+M.created):'';
const stageIdx={gis:0,before:1,after:3}[kind];
$('stages').innerHTML=(M.stages||[]).map((s,i)=>`<div class="stage${i===stageIdx?' on':''}"><span class="n">${i+1}</span>${esc(s[1])}</div>`).join('');

/* drawing */
const world=$('world');
function draw(){
  world.innerHTML='';
  const gC=el('g',{},world),gL=el('g',{},world),gN=el('g',{},world),gD=el('g',{},world);
  cables.forEach(c=>{
    const on=sel.kind==='cable'&&sel.id===c.id;
    const dim=(phase!=='전체'&&!(c.phases||[]).includes(phase))||(query&&!hits.has('c:'+c.id));
    const g=el('g',{class:'cable'+(dim?' dim':''),'data-id':c.id},gC);
    (c.rims||[]).forEach(r=>el('path',{d:c.d,fill:'none',stroke:r[0],'stroke-width':r[1]},g));
    if(on)el('path',{d:c.d,fill:'none',stroke:'#b9f6ca','stroke-width':14,'stroke-dasharray':c.dash?'28 14':null},g);
    if(query&&hits.has('c:'+c.id))el('path',{d:c.d,fill:'none',stroke:'#ffd54f','stroke-width':16,'stroke-opacity':.8},g);
    el('path',{d:c.d,fill:'none',stroke:on?'#00a843':c.color,'stroke-width':on?7:4,'stroke-dasharray':c.dash?(on?'30 14':'16 8'):null},g);
    (c.marks||[]).forEach(m=>{
      if(m[0]==='x')el('path',{d:`M ${m[1]-9} ${m[2]-9} L ${m[1]+9} ${m[2]+9} M ${m[1]-9} ${m[2]+9} L ${m[1]+9} ${m[2]-9}`,fill:'none',stroke:'#111','stroke-width':3},g);
      else el('polygon',{points:star(m[1],m[2],12,5.5),fill:'#ff1744',stroke:'#111','stroke-width':2},g);
    });
    el('path',{d:c.d,fill:'none',stroke:'transparent','stroke-width':22},g);
    g.addEventListener('click',e=>{e.stopPropagation();select('cable',c.id)});
  });
  labels.forEach(L=>{
    const c=C[L.id];if(!c)return;
    const on=sel.kind==='cable'&&sel.id===L.id;
    const dim=(phase!=='전체'&&!(c.phases||[]).includes(phase))||(query&&!hits.has('c:'+c.id));
    const g=el('g',{class:'lbl cable'+(dim?' dim':'')},gL);
    const f=L.parts[0];
    if(Math.hypot(f.x-L.ax,f.y-L.ay)>1)el('line',{x1:L.ax,y1:L.ay,x2:f.x,y2:f.y,stroke:'#64748b','stroke-dasharray':'3 3'},g);
    L.parts.forEach((p,i)=>{
      el('rect',{x:p.x-p.w/2,y:p.y-p.h/2,width:p.w,height:p.h,rx:4,fill:p.fill,stroke:on&&i===0?'#00a843':p.border,'stroke-width':on&&i===0?2.5:1.5},g);
      const t=el('text',{x:p.x,y:p.y,'dominant-baseline':'central','text-anchor':'middle','font-size':p.size,'font-weight':'bold',fill:on&&i===0?'#006b2c':p.ink,'font-family':'var(--font)'},g);t.textContent=p.text;
    });
    g.addEventListener('click',e=>{e.stopPropagation();select('cable',L.id)});
  });
  nodes.forEach(n=>{
    const on=sel.kind==='node'&&sel.id===n.id,v=n.v||{},x=n.x,y=n.y;
    const dim=query&&!hits.has('n:'+n.id);
    const g=el('g',{class:'node'+(dim?' dim':'')},gN);
    if(n.ring)el('circle',{cx:x,cy:y,r:39,fill:'none',stroke:n.ring,'stroke-width':5},g);
    if(on)el('circle',{cx:x,cy:y,r:44,fill:'none',stroke:'#00a843','stroke-width':3,'stroke-dasharray':'6 4'},g);
    if(query&&hits.has('n:'+n.id))el('circle',{cx:x,cy:y,r:46,fill:'#ffd54f','fill-opacity':.45},g);
    if(n.type==='sub'){
      if(n.poly){el('polygon',{points:n.poly,fill:v.fill,stroke:'#fff','stroke-width':12,'stroke-linejoin':'miter'},g);el('polygon',{points:n.poly,fill:v.fill,stroke:v.outline,'stroke-width':3},g)}
      else{el('circle',{cx:x,cy:y,r:27,fill:v.fill,stroke:'#fff','stroke-width':12},g);el('circle',{cx:x,cy:y,r:27,fill:v.fill,stroke:v.outline,'stroke-width':3},g)}
    }else if(v.shape==='wide')el('rect',{x:x-60,y:y-32,width:120,height:64,fill:v.fill,stroke:v.outline,'stroke-width':3},g);
    else el('circle',{cx:x,cy:y,r:32,fill:v.fill,stroke:v.outline,'stroke-width':3},g);
    if(v.shape==='circle_x')el('path',{d:`M ${x-22} ${y-22} L ${x+22} ${y+22} M ${x-22} ${y+22} L ${x+22} ${y-22}`,fill:'none',stroke:v.outline,'stroke-width':4},g);
    if(v.symbol_font){const t=el('text',{x,y,'dominant-baseline':'central','text-anchor':'middle','font-family':'Arial','font-size':v.symbol_font,'font-weight':'bold',fill:v.text_fill},g);t.textContent=v.text}
    else if(v.text){const t=el('text',{x,y:y+6,'text-anchor':'middle','font-size':18,'font-weight':'bold',fill:v.text_fill,'font-family':'var(--font)'},g);t.textContent=v.text}
    if(v.label_above!==false){
      const name=n.name||'',lw=Math.max(56,Math.min(220,name.length*13+16));
      el('rect',{x:x-lw/2,y:y-61,width:lw,height:24,rx:5,fill:n.name_fill||'#fff',stroke:n.border||'#1565c0','stroke-width':2},g);
      const t=el('text',{x,y:y-49,'dominant-baseline':'central','text-anchor':'middle','font-size':12,'font-weight':'bold',fill:n.name_ink||'#222','font-family':'var(--font)'},g);t.textContent=name;
    }
    (n.badges||[]).forEach((b,i)=>{
      const by=y+48+24*i,bw=Math.max(70,b[0].length*11+12);
      el('rect',{x:x-bw/2,y:by-10,width:bw,height:20,rx:9,fill:b[1],stroke:'#fff'},g);
      const t=el('text',{x,y:by,'dominant-baseline':'central','text-anchor':'middle','font-size':10.5,'font-weight':'bold',fill:b[2],'font-family':'var(--font)'},g);t.textContent=b[0];
    });
    g.addEventListener('click',e=>{e.stopPropagation();select('node',n.id)});
  });
  details.forEach(d=>{
    el('rect',{x:d.x-d.w/2,y:d.y-d.h/2,width:d.w,height:d.h,fill:'#f1f7ff',stroke:d.border},gD);
    const t=el('text',{x:d.x,y:d.y,'dominant-baseline':'central','text-anchor':'middle','font-size':d.size,'font-weight':'bold',fill:'#17365d','font-family':'var(--font)'},gD);t.textContent=d.text;
  });
}
function star(cx,cy,o,i){const p=[];for(let k=0;k<10;k++){const r=k%2?i:o,a=-Math.PI/2+k*Math.PI/5;p.push((cx+Math.cos(a)*r).toFixed(1)+','+(cy+Math.sin(a)*r).toFixed(1))}return p.join(' ')}

/* pan & zoom */
const svg=$('map'),B=D.bounds||[0,0,1200,800];
let view={x:B[0],y:B[1],w:B[2]-B[0],h:B[3]-B[1]},base=1;
function applyView(){svg.setAttribute('viewBox',`${view.x} ${view.y} ${view.w} ${view.h}`);svg.setAttribute('preserveAspectRatio','xMidYMid meet');$('pct').textContent=Math.round(100*base/view.w)+'%'}
function fit(){
  const r=svg.getBoundingClientRect(),bw=B[2]-B[0],bh=B[3]-B[1];
  const padL=320,padR=20,padT=70,padB=60,aw=Math.max(200,r.width-padL-padR),ah=Math.max(200,r.height-padT-padB);
  const s=Math.min(aw/bw,ah/bh,1.6);
  view.w=r.width/s;view.h=r.height/s;view.x=B[0]-(padL+(aw-bw*s)/2)/s;view.y=B[1]-(padT+(ah-bh*s)/2)/s;base=view.w;applyView();
}
function zoomAt(f,cx,cy){const r=svg.getBoundingClientRect();const px=view.x+(cx-r.left)/r.width*view.w,py=view.y+(cy-r.top)/r.height*view.h;view.w*=f;view.h*=f;view.x=px-(cx-r.left)/r.width*view.w;view.y=py-(cy-r.top)/r.height*view.h;applyView()}
svg.addEventListener('wheel',e=>{e.preventDefault();zoomAt(e.deltaY>0?1.15:1/1.15,e.clientX,e.clientY)},{passive:false});
let drag=null;
svg.addEventListener('mousedown',e=>{drag={x:e.clientX,y:e.clientY,vx:view.x,vy:view.y,moved:false};svg.classList.add('drag')});
window.addEventListener('mousemove',e=>{if(!drag)return;const r=svg.getBoundingClientRect();const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true;view.x=drag.vx-dx/r.width*view.w;view.y=drag.vy-dy/r.height*view.h;applyView()});
window.addEventListener('mouseup',()=>{svg.classList.remove('drag');setTimeout(()=>drag=null,0)});
svg.addEventListener('click',()=>{if(drag&&drag.moved)return;select(null,null)},true);
$('zin').onclick=()=>{const r=svg.getBoundingClientRect();zoomAt(1/1.25,r.left+r.width/2,r.top+r.height/2)};
$('zout').onclick=()=>{const r=svg.getBoundingClientRect();zoomAt(1.25,r.left+r.width/2,r.top+r.height/2)};
$('fit').onclick=fit;window.addEventListener('resize',fit);

/* selection */
function select(k,id){
  if(drag&&drag.moved)return;
  sel={kind:k,id};draw();renderSide();
}
function focusOn(x,y){view.x=x-view.w/2+160*view.w/svg.getBoundingClientRect().width;view.y=y-view.h/2;applyView()}

/* dashboard */
let dashMode='work';
function pct(v){return v==null?'-':(Math.round(v*10)/10)+'%'}
function renderDash(){
  const d=D.dashboard||{},el2=$('dash');const closed=el2.classList.contains('closed');
  let body;
  if(dashMode==='work'){
    const inc=Math.max(0,(d.total||0)-(d.done||0)),total=d.total||0;
    body=d.note&&!d.all?`<div class="rate"><span class="big" style="font-size:20px">대상 없음</span></div><div class="dash-note">${esc(d.note)}</div>`:
    `<div class="rate"><span class="big">${pct(d.rate)}</span><span class="of">연결 완료 · 대상 ${total}개 중 ${d.done||0}개</span></div>
     <div class="bar"><i style="width:${total?100*(d.done||0)/total:0}%;background:var(--ok)"></i><i style="width:${total?100*inc/total:0}%;background:var(--need)"></i></div>
     <div class="kpis"><div class="kpi" style="--c:#d32f2f"><span>절단절체</span><b>${d.cut||0}<small>코어</small></b></div>
     <div class="kpi" style="--c:#2f5fc4"><span>코어절체</span><b>${d.transfer||0}<small>코어</small></b></div>
     <div class="kpi" style="--c:var(--need)"><span>미완료</span><b>${inc}<small>코어</small></b></div>
     <div class="kpi" style="--c:#64748b"><span>작업코어 전체</span><b>${d.all||0}<small>코어</small></b></div></div>`;
  }else{
    const t=d.drawing_total||0,dn=d.drawing_done||0;
    body=`<div class="rate"><span class="big">${pct(d.drawing_rate)}</span><span class="of">필수 코어 연결 완료율</span></div>
     <div class="bar"><i style="width:${t?100*dn/t:0}%;background:var(--ok)"></i><i style="width:${t?100*(t-dn)/t:0}%;background:var(--need)"></i></div>
     <div class="kpis"><div class="kpi" style="--c:var(--ok)"><span>연결 완료</span><b>${dn}<small>코어</small></b></div><div class="kpi" style="--c:var(--need)"><span>미완료</span><b>${t-dn}<small>코어</small></b></div></div>`;
  }
  el2.innerHTML=`<div class="dash-h"><b>${dashMode==='work'?'작업코어 현황':'도면 현황'}</b><div class="seg"><button data-m="work" class="${dashMode==='work'?'on':''}">작업</button><button data-m="drawing" class="${dashMode==='drawing'?'on':''}">도면</button></div><button class="icon-btn" id="dtog" title="접기/펼치기">${closed?'▼':'▲'}</button></div>
   <div class="dash-b">${body}</div><div class="dash-f ${d.errors?'badf':'good'}">오류코어 ${d.errors||0}개</div>`;
  el2.querySelectorAll('.seg button').forEach(b=>b.onclick=()=>{dashMode=b.dataset.m;renderDash()});
  $('dtog').onclick=()=>{el2.classList.toggle('closed');renderDash()};
}

/* phase filter */
function renderPhases(){
  const bar=$('phasebar');
  if(!phaseNames.length){bar.style.display='none';return}
  bar.innerHTML='<span class="t">작업차수</span>'+['전체',...phaseNames].map(p=>{
    const cnt=p==='전체'?cables.length:cables.filter(c=>(c.phases||[]).includes(p)).length;
    return `<button class="chip${p===phase?' on':''}" data-p="${esc(p)}">${p!=='전체'?`<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${PC(p)};margin-right:5px"></span>`:''}${esc(p)}<span class="cnt">${cnt}</span></button>`}).join('');
  bar.querySelectorAll('button').forEach(b=>b.onclick=()=>{phase=b.dataset.p;renderPhases();draw()});
}

/* legend */
function renderLegend(){
  const line=(c,dash)=>`<svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="${c}" stroke-width="4"${dash?' stroke-dasharray="9 5"':''}/></svg>`;
  $('legend').innerHTML=`<span class="grp">규격</span>`+[['#d32f2f','~12C'],['#1769aa','~36C'],['#19703a','~72C'],['#e24a9b','~144C'],['#795548','그 이상']].map(x=>`<span class="sw">${line(x[0])}${x[1]}</span>`).join('')+
   `<span class="grp">· 상태</span><span class="sw">${line('#475569',true)}신설</span><span class="sw"><svg width="18" height="18"><polygon points="${star(9,9,8,3.6)}" fill="#ff1744" stroke="#111" stroke-width="1.4"/></svg>절단</span><span class="sw"><svg width="16" height="16"><path d="M3 3L13 13M3 13L13 3" stroke="#111" stroke-width="2.4"/></svg>철거</span>`;
}

/* side panel */
function statusOf(c){return STATUS_C[c.status]?c.status:'기설'}
function renderSide(){
  const side=$('side');
  if(sel.kind==='cable'&&C[sel.id])return renderCable(C[sel.id]);
  if(sel.kind==='node'&&N[sel.id])return renderNode(N[sel.id]);
  const st={};cables.forEach(c=>{const s=statusOf(c);st[s]=(st[s]||0)+1});
  side.innerHTML=`<div class="side-h"><div class="crumb">도면 요약</div><div class="title-row"><h2>${esc(M.name||'')}</h2><span class="pill" style="--c:var(--stage)">${esc(stageLabel)}</span></div>
   <div class="meta"><div><span>함체·RN</span><b>${nodes.filter(n=>n.type!=='sub').length}</b></div><div><span>가입자</span><b>${nodes.filter(n=>n.type==='sub').length}</b></div><div><span>케이블</span><b>${cables.length}</b></div></div></div>
   <div class="split">${Object.entries(st).map(([k,v])=>`<span class="chip" style="--c:${STATUS_C[k]}"><i></i>${k} <b>${v}</b></span>`).join('')}</div>
   <div class="empty">도면에서 <b>케이블</b>을 누르면 코어 목록이,<br><b>함체</b>를 누르면 연결된 케이블이 여기에 나옵니다.<br><br>마우스 휠: 확대·축소 · 끌기: 화면 이동<br>위쪽 찾기 칸에 코어ID를 넣으면 지나가는 케이블이 노랗게 표시됩니다.</div>
   ${matchList()}`;
  bindList(side);
}
function matchList(){
  if(!query)return'';
  const cs=cables.filter(c=>hits.has('c:'+c.id)),ns=nodes.filter(n=>hits.has('n:'+n.id));
  if(!cs.length&&!ns.length)return `<div class="side-f">「${esc(query)}」 찾은 결과 없음</div>`;
  return `<div class="list"><div class="crumb" style="margin:4px 2px 8px">「${esc(query)}」 찾은 결과 · 케이블 ${cs.length} · 시설 ${ns.length}</div>`+
   cs.map(c=>`<button data-c="${esc(c.id)}"><i style="--c:${c.color}"></i>${esc(cableName(c))}<span class="r">${esc((N[c.a]||{}).name||'')} ↔ ${esc((N[c.b]||{}).name||'')}</span></button>`).join('')+
   ns.map(n=>`<button data-n="${esc(n.id)}"><i style="--c:${n.border||'#1565c0'}"></i>${esc(n.name)}<span class="r">${esc(n.type_label||'')}</span></button>`).join('')+'</div>';
}
function bindList(root){
  root.querySelectorAll('[data-c]').forEach(b=>b.onclick=()=>{const c=C[b.dataset.c];select('cable',c.id);const p=c.mid;if(p)focusOn(p[0],p[1])});
  root.querySelectorAll('[data-n]').forEach(b=>b.onclick=()=>{const n=N[b.dataset.n];select('node',n.id);focusOn(n.x,n.y)});
}
function cableName(c){return (c.spec||'')+(c.cable_id?' ('+c.cable_id+')':'')}
function renderCable(c){
  const rows=cores[c.id]||[],used=rows.filter(r=>r.id).length;
  const cnt={};rows.forEach(r=>{const k=r.method||(r.id?'':'빈코어');if(k)cnt[k]=(cnt[k]||0)+1});
  const done=rows.filter(r=>r.done===true).length,notdone=rows.filter(r=>r.done===false).length;
  const s=statusOf(c);
  $('side').innerHTML=`<div class="side-h"><div class="crumb">케이블 · ${esc((N[c.a]||{}).name||'?')} ↔ ${esc((N[c.b]||{}).name||'?')}</div>
   <div class="title-row"><h2>${esc(cableName(c))}</h2><span class="pill" style="--c:${STATUS_C[s]}">${esc(c.status||'기설')}</span>${(c.phases||[]).map(p=>`<span class="pill" style="--c:${PC(p)}">${esc(p)}</span>`).join('')}</div>
   <div class="meta"><div><span>규격</span><b>${esc(c.spec)}</b></div><div><span>LOT</span><b>${esc(c.lot||'-')}</b></div><div><span>사용 코어</span><b>${used} / ${c.size||rows.length}</b></div></div></div>
   <div class="split">${Object.entries(cnt).map(([k,v])=>`<span class="chip" style="--c:${METHOD_C[k]||'#cbd5e1'}"><i></i>${esc(k)} <b>${v}</b></span>`).join('')}
    ${done?`<span class="chip" style="--c:var(--ok)"><i></i>연결 완료 <b>${done}</b></span>`:''}${notdone?`<span class="chip" style="--c:var(--need)"><i></i>미완료 <b>${notdone}</b></span>`:''}</div>
   <div class="table-wrap"><table><thead><tr><th>#</th><th>색</th><th>코어ID · 내역</th><th>분배</th><th>연결</th><th>차수</th></tr></thead><tbody>
   ${rows.map(r=>{const f=FIBER[(Math.max(1,r.n)-1)%12];const hit=query&&hitCores.has(c.id+'#'+r.n);
     const lab=(r.labels||[]).length?`<span class="sub">[${r.labels.map(esc).join('] [')}]</span>`:'';
     const det=r.detail?`<span class="sub">${esc(r.detail)}</span>`:'';
     const dn=r.done===true?'<span class="done" style="color:var(--ok)">완료</span>':r.done===false?`<span class="done" style="color:var(--bad)" title="${esc(r.reason)}">미완료</span>`:'<span style="color:#cbd5e1">-</span>';
     return `<tr class="${hit?'hit':''}" title="${esc(r.reason||'')}"><td class="no">${r.n}</td><td><span class="fc"><i style="--c:${f[1]}"></i>${f[0]}</span></td>
       <td class="cid">${r.id?esc(r.id):'<span style="color:#cbd5e1">-</span>'}${det}${lab}</td>
       <td>${r.method?`<span class="st" style="--c:${METHOD_C[r.method]||'#64748b'}">${esc(r.method)}</span>`:''}</td><td>${dn}</td>
       <td>${(r.phases||[]).map(p=>`<span class="ph-tag" style="--c:${PC(p)}">${esc(p)}</span>`).join('')}</td></tr>`}).join('')}
   </tbody></table>${rows.length?'':'<div class="empty">입력된 코어가 없습니다.</div>'}</div>
   <div class="side-f">코어 색은 표준 12색 순서(청·등·녹…)로 보여 줍니다 · 미완료에 마우스를 올리면 이유가 보입니다</div>`;
  const first=$('side').querySelector('tr.hit');if(first)first.scrollIntoView({block:'center'});
}
function renderNode(n){
  const list=cables.filter(c=>c.a===n.id||c.b===n.id);
  $('side').innerHTML=`<div class="side-h"><div class="crumb">${esc(n.type_label||'시설')}</div>
   <div class="title-row"><h2>${esc(n.name)}</h2><span class="pill" style="--c:${n.border||'#1565c0'}">${esc(n.status||'기설')}</span></div>
   ${n.detail?`<div class="crumb" style="margin-top:6px">${esc(n.detail)}</div>`:''}
   <div class="split" style="border:0">${(n.badges||[]).map(b=>`<span class="st" style="--c:${b[1]};color:${b[2]}">${esc(b[0])}</span>`).join('')}</div></div>
   <div class="list"><div class="crumb" style="margin:4px 2px 8px">연결된 케이블 ${list.length}개</div>
   ${list.map(c=>{const o=N[c.a===n.id?c.b:c.a]||{};return `<button data-c="${esc(c.id)}"><i style="--c:${c.color}"></i>${esc(cableName(c))} <span class="pill" style="--c:${STATUS_C[statusOf(c)]};font-size:10px">${esc(c.status||'기설')}</span><span class="r">→ ${esc(o.name||'')}</span></button>`}).join('')}</div>`;
  bindList($('side'));
}

/* search */
$('q').addEventListener('input',e=>{
  query=e.target.value.trim();hits=new Set();hitCores=new Set();
  if(query){
    const q=query.toLowerCase();
    for(const c of cables){
      if(cableName(c).toLowerCase().includes(q)||(c.lot||'').toLowerCase().includes(q))hits.add('c:'+c.id);
      for(const r of cores[c.id]||[]){if(r.id&&r.id.toLowerCase().includes(q)){hits.add('c:'+c.id);hitCores.add(c.id+'#'+r.n);hits.add('n:'+c.a);hits.add('n:'+c.b)}}
    }
    for(const n of nodes)if((n.name||'').toLowerCase().includes(q))hits.add('n:'+n.id);
  }
  draw();renderSide();
});

/* footer */
function renderFoot(){
  const st={};cables.forEach(c=>{const s=statusOf(c);st[s]=(st[s]||0)+1});
  $('foot').innerHTML=`<span>단계 <b>${esc(stageLabel)}</b></span><span>함체·RN <b>${nodes.filter(n=>n.type!=='sub').length}</b> · 가입자 <b>${nodes.filter(n=>n.type==='sub').length}</b></span><span>케이블 <b>${cables.length}</b> (${Object.entries(st).map(([k,v])=>k+' '+v).join(' · ')})</span><span class="r">보기 전용 · 수정은 기존 프로그램 화면에서</span>`;
}

renderDash();renderPhases();renderLegend();renderFoot();draw();renderSide();fit();
</script>
</body>
</html>
'''
