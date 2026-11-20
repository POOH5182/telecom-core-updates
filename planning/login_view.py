"""V216: Google 로그인 in the browser (HTML).

The login window (CloudLogin) starts a page server that only this PC can
reach. The page shows the same login, 승인 확인 and 로그인 유지 options as the
window; the buttons run the window's own methods, so the Google PKCE login,
admin approval and saved-login rules stay the same. After approval the page
waits for the 작업도면 and moves to it in the same tab.

- login_view_state(): the shared dict (read by the page server thread)
- login_view_document(meta): the page
"""


LOGIN_VIEW_START_FILE='work_view_start.json'


def login_view_state():
    return {'info':'','email':'','status':'','busy':False,'approved':False,'closed':False,
            'next':'','taken':False,'message':'','remember':True,'tk_closed':False}


def login_view_enabled(home):
    """Same switch as 「시작할 때 HTML 작업도면 열기」 (default on)."""
    try:
        path=Path(home)/'data'/LOGIN_VIEW_START_FILE
        return bool(json.loads(path.read_text(encoding='utf-8')).get('open_on_start',True))
    except (OSError,ValueError,AttributeError):return True


def login_view_status(state):
    """Snapshot for the page; hands over the 작업도면 address once."""
    value={k:state.get(k) for k in ('info','email','status','busy','approved','closed','message','remember')}
    if state.get('next'):
        value['next']=state['next'];state['taken']=True
    return value


def login_view_document(meta):
    return LOGIN_VIEW_TEMPLATE.replace('__DATA__',html_view_json(meta))


LOGIN_VIEW_TEMPLATE=r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>통신 코어 도면 · 로그인</title>
<style>
:root{--navy:#172033;--ink:#172033;--ink-2:#334155;--ink-3:#64748b;--line:#dbe3ee;--accent:#2f5fc4;--ok:#15803d;--warn:#b45309;--bad:#c62828;
  --font:"Pretendard","Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",system-ui,sans-serif}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{font-family:var(--font);background:radial-gradient(1200px 600px at 20% -10%,#2b3b5e 0,var(--navy) 55%,#0f1626 100%);color:var(--ink);display:flex;align-items:center;justify-content:center;padding:16px}
.card{width:100%;max-width:440px;background:#fff;border-radius:18px;box-shadow:0 24px 60px rgba(0,0,0,.35);padding:34px 32px 26px}
.brand{display:flex;align-items:center;gap:12px;margin-bottom:22px}
.brand b{font-size:21px;display:block}.brand small{color:var(--ink-3);font-size:12.5px}
p.lead{margin:0 0 20px;color:var(--ink-2);font-size:14px;line-height:1.6}
button.google{width:100%;display:flex;align-items:center;justify-content:center;gap:10px;font:inherit;font-size:15px;font-weight:700;padding:13px 16px;border-radius:10px;border:1px solid #c9d3e2;background:#fff;color:var(--ink);cursor:pointer}
button.google:hover{background:#f5f8fd;border-color:var(--accent)}
button:disabled{opacity:.55;cursor:wait}
.row{display:flex;align-items:center;justify-content:space-between;margin:14px 2px 0;font-size:13px;color:var(--ink-2)}
.row label{display:flex;align-items:center;gap:7px;cursor:pointer}
.link{background:none;border:0;color:var(--accent);font:inherit;font-size:13px;cursor:pointer;padding:4px}
.state{margin-top:20px;border-radius:10px;padding:12px 14px;font-size:13.5px;line-height:1.55;background:#fff8e6;color:#7a4b00;border:1px solid #f5d48a;white-space:pre-line;min-height:46px}
.state.ok{background:#ecfdf3;color:#14532d;border-color:#9fe0b6}
.state.bad{background:#fdecec;color:#7f1d1d;border-color:#f3b4b4}
.spin{display:inline-block;width:13px;height:13px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:s 0.8s linear infinite;vertical-align:-2px;margin-right:6px}
@keyframes s{to{transform:rotate(360deg)}}
.foot{margin-top:18px;font-size:11.5px;color:var(--ink-3);display:flex;justify-content:space-between;gap:8px}
</style>
</head>
<body>
<main class="card">
  <div class="brand">
    <svg width="38" height="38" viewBox="0 0 30 30" fill="none" stroke="#2f5fc4" stroke-width="1.8"><circle cx="7" cy="7" r="4"/><circle cx="23" cy="7" r="4"/><circle cx="7" cy="23" r="4"/><circle cx="23" cy="23" r="4"/><path d="M11 7h8M7 11v8M23 11v8M11 23h8"/></svg>
    <div><b>통신 코어 도면</b><small id="ver"></small></div>
  </div>
  <p class="lead">Google 계정으로 로그인하고 내 도면을 이어서 작업하세요.<br>처음 로그인한 사용자는 관리자 승인이 필요합니다.</p>
  <button class="google" id="login"><svg width="18" height="18" viewBox="0 0 48 48"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/></svg>Google 계정으로 로그인</button>
  <div class="row"><label><input type="checkbox" id="remember" checked> 이 PC에서 로그인 유지</label><button class="link" id="check">승인 상태 다시 확인</button></div>
  <div class="state" id="state">프로그램과 연결하는 중…</div>
  <div class="foot"><span>로그인 창(기존 화면)에서도 똑같이 할 수 있어요</span><button class="link" id="showTk" style="font-size:11.5px">로그인 창 보기</button></div>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const M=JSON.parse(document.getElementById('data').textContent);const $=id=>document.getElementById(id);
$('ver').textContent='버전 '+(M.version||'');
let rememberTouched=false,lost=0,last={};
async function api(name,body){
  const res=await fetch('/api/'+name,{method:body===undefined?'GET':'POST',headers:{'X-Telecom-Token':M.token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
  return res.json();
}
function show(s){
  last=s;const box=$('state');let text=s.info||'',cls='state';
  if(s.next){box.className='state ok';box.innerHTML='<span class="spin"></span>로그인 완료 · 작업도면으로 이동해요';location.replace(s.next);return}
  if(s.approved){cls+=' ok';text=(s.email?s.email+'\n':'')+(s.message||'로그인 완료 · 작업도면을 여는 중…')}
  else if(s.closed){cls+=' bad';text='로그인 창이 닫혔어요. 프로그램을 다시 실행하세요.'}
  else if(s.status==='pending'||s.status==='blocked'){cls+=' bad'}
  box.className=cls;box.innerHTML=(s.busy||(s.approved&&!s.message)?'<span class="spin"></span>':'')+text.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  $('login').disabled=!!(s.busy||s.approved||s.closed);$('check').disabled=!!(s.busy||s.approved||s.closed);
  if(!rememberTouched)$('remember').checked=s.remember!==false;
}
async function poll(){
  try{const s=await api('status');lost=0;if(s.ok===false)throw 0;show(s.value||s)}
  catch(e){if(++lost>4&&!last.approved){$('state').className='state bad';$('state').textContent='프로그램과 연결이 끊겼어요. 프로그램이 켜져 있는지 확인하세요.'}}
  if(!last.next)setTimeout(poll,last.approved?500:1000);
}
$('remember').onchange=()=>{rememberTouched=true};
$('login').onclick=async()=>{$('login').disabled=true;try{const r=await api('login',{remember:$('remember').checked});if(r.ok===false)show(Object.assign({},last,{info:r.error}))}catch(e){}};
$('check').onclick=async()=>{try{const r=await api('check',{});if(r.ok===false)show(Object.assign({},last,{info:r.error}))}catch(e){}};
$('showTk').onclick=()=>api('show',{}).catch(()=>{});
poll();
</script>
</body>
</html>
'''
