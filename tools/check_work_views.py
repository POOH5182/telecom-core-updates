"""V208: 작업도면 전·중·후 (HTML, read-only).

One drawing made from 현장반영 (작업전) + 후도면 (작업후). Every core slot keeps
both assignments, so renumbering a 기설 cable (1.2.5.6.7 -> 1.2.3.4.5) shows as
코어절체 / 새로 배정 / 해제, never as an error. Duplicate checks run inside each
view only; 철거 cores with no 작업후 path are listed as 끊긴 코어. Making the page
never writes either drawing file."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from check_field_survey import code,wf


def embedded(text):
    match=re.search(r'<script id="data" type="application/json">(.*?)</script>',text,re.S)
    assert match,'data block missing'
    return json.loads(match.group(1))


def put(store,cable,number,core_id):
    if not store.conn.execute('UPDATE cores SET core_id=? WHERE cable_id=? AND core_index=?',(core_id,cable,number)).rowcount:
        store.conn.execute("INSERT INTO cores(cable_id,core_index,core_id) VALUES(?,?,?)",(cable,number,core_id))
    store.conn.commit()


class FakeApp:
    work_view_stores=code['App'].work_view_stores
    work_view_scene=code['App'].work_view_scene
    work_view_text=code['App'].work_view_text
    work_view_live_scene=code['App'].work_view_live_scene
    work_view_edit_core=code['App'].work_view_edit_core
    work_view_edit=code['App'].work_view_edit
    work_view_apply=code['App'].work_view_apply
    work_view_trace=code['App'].work_view_trace
    work_view_backup=code['App'].work_view_backup
    work_view_switch=code['App'].work_view_switch
    def work_view_show_app(self,payload=None):self.shown=getattr(self,'shown',0)+1;return {'ok':True}
    def after(self,ms,fn):self.later=getattr(self,'later',[])+[fn]
    def load_scenario(self,kind):self.switched=kind;return True
    def scenario_folder(self):return self.folder
    def refresh(self):self.refreshed=getattr(self,'refreshed',0)+1
    def save_current_drawing(self,silent=False):self.saved=getattr(self,'saved',0)+1
    status=SimpleNamespace(set=lambda text:None)
    def __init__(self,store,kind,folder):
        self.store=store;self.kind=kind;self.folder=folder;self.cloud=None
    def scenario_kind(self):return self.kind
    def scenario_path(self,kind):return self.folder/(kind+'.sqlite3')
    def work_report(self):return {'rows':[{'method':'코어절체','core_id':'X5','source_slots':[(self.cable_k,3)]}]}


class WorkViewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        b=self.before=code['Store'](self.folder/'before.sqlite3')
        b.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','before')");b.conn.commit()
        self.na=b.add_node('MDF',0,0);self.nb=b.add_node('함체 B',300,0);self.nc=b.add_node('함체 C',300,300)
        self.k=b.add_cable(self.na,self.nb,'K','12C','기설');self.r=b.add_cable(self.nb,self.nc,'R','12C','철거')
        for n,cid in ((1,'X1'),(2,'X2'),(5,'X5'),(6,'X6'),(7,'X7')):put(b,self.k,n,cid)
        put(b,self.r,1,'R1');put(b,self.r,2,'R2')
        b.backup_to(self.folder/'after.sqlite3')
        a=self.after=code['Store'](self.folder/'after.sqlite3')
        a.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','after')");a.conn.commit()
        for n in range(1,13):put(a,self.k,n,'')
        for n,cid in ((1,'X1'),(2,'X2'),(3,'X5'),(4,'X6'),(5,'X7'),(8,'X1')):put(a,self.k,n,cid)
        self.s=a.add_cable(self.nb,self.nc,'S','12C','신설');put(a,self.s,1,'R1')
    def tearDown(self):
        self.before.close();self.after.close();self.temp.cleanup()

    def test_roles_and_states(self):
        self.assertEqual(wf.work_view_role('기설','기설'),'기설')
        self.assertEqual(wf.work_view_role('철거','철거'),'철거')
        self.assertEqual(wf.work_view_role('기설','절단'),'절단')
        self.assertEqual(wf.work_view_role(None,'신설'),'신설')
        self.assertEqual(wf.work_view_role('기설',None),'철거','deleted in 후도면 = 철거')
        self.assertEqual(wf.work_view_role('기설',None,has_after=False),'기설')
        self.assertEqual(wf.work_view_state('기설','A','a '),'유지')
        self.assertEqual(wf.work_view_state('기설','5','3'),'코어절체')
        self.assertEqual(wf.work_view_state('기설','5',''),'해제')
        self.assertEqual(wf.work_view_state('기설','','3'),'신규배정')
        self.assertEqual(wf.work_view_state('철거','R1','R1'),'철거')
        self.assertEqual(wf.work_view_state('신설','','R1'),'신설')
        print('PASS cable roles and slot states (keep / transfer / new / released)')

    def test_renumbered_cable_is_transfer_not_error(self):
        data=wf.work_view_data(self.before,self.after,{'rows':[]})
        roles={c['id']:c['role'] for c in data['cables']}
        self.assertEqual((roles[self.k],roles[self.r],roles[self.s]),('기설','철거','신설'))
        rows={r['n']:r for r in data['cores'][self.k]}
        self.assertEqual((rows[1]['s'],rows[2]['s']),('유지','유지'))
        self.assertEqual((rows[5]['b'],rows[5]['a'],rows[5]['s']),('X5','X7','코어절체'))
        self.assertEqual((rows[3]['s'],rows[4]['s']),('신규배정','신규배정'))
        self.assertEqual((rows[6]['s'],rows[7]['s']),('해제','해제'))
        before_issues=data['issues']['before'];after_issues=data['issues']['after']
        self.assertEqual(before_issues,[],'작업전 has no duplicate: renumbering is not an error')
        dup=[i for i in after_issues if i['kind']=='중복']
        self.assertEqual(len(dup),1);self.assertEqual((dup[0]['cable'],dup[0]['n'],dup[0]['id']),(self.k,[1,8],'X1'))
        broken=data['issues']['broken']
        self.assertEqual([(i['id'],i['cable']) for i in broken],[('R2',self.r)],'R1 moved to 신설 S, R2 has no 작업후 path')
        self.assertEqual(data['counts']['states']['코어절체'],1)
        self.assertEqual(data['counts']['broken'],1)
        print('PASS renumbered existing cable shows core transfer, duplicates checked per view, broken cores listed')

    def test_page_from_app_is_safe_and_read_only(self):
        put(self.before,self.k,9,'</script><b>x');self.before.conn.commit()
        app=FakeApp(self.after,'after',self.folder);app.cable_k=self.k
        changes=self.after.conn.total_changes
        self.before.close();self.before=code['Store'](self.folder/'before.sqlite3')
        stamp=(self.folder/'before.sqlite3').read_bytes()
        text=app.work_view_text()
        self.assertEqual((self.folder/'before.sqlite3').read_bytes(),stamp,'saved 현장반영 file must not change')
        self.assertEqual(self.after.conn.total_changes,changes,'open drawing must not change')
        self.assertEqual(text.count('</script>'),2)
        self.assertNotIn('__DATA__',text);self.assertNotIn('__TITLE__',text)
        self.assertNotIn('https://',text);self.assertNotIn('http://',text.replace('http://www.w3.org/2000/svg',''))
        data=embedded(text)
        cables={c['id']:c for c in data['cables']}
        self.assertEqual(set(cables),{self.k,self.r,self.s})
        self.assertTrue(cables[self.r]['marks'] and not cables[self.s]['marks'])
        self.assertNotEqual(cables[self.r]['d'],cables[self.s]['d'],'철거 and 신설 between the same nodes run side by side')
        self.assertEqual({r['n']:r for r in data['cores'][self.k]}[9]['b'],'</script><b>x')
        self.assertEqual({r['n']:r for r in data['cores'][self.k]}[3]['m'],'코어절체')
        self.assertTrue(data['has_after']);self.assertEqual(data['meta']['modes'][1][1],'작업중')
        self.assertEqual(data['meta']['version'],code['APP_TITLE'].rsplit('V',1)[-1])
        print('PASS work drawing page joins field + after drawings, escapes text, stays offline and never writes')

    def test_open_from_field_drawing_without_after(self):
        app=FakeApp(self.before,'before',self.folder/'none');(self.folder/'none').mkdir()
        app.cable_k=self.k
        data=embedded(app.work_view_text())
        self.assertFalse(data['has_after'])
        rows={r['n']:r for r in data['cores'][self.k]}
        self.assertEqual((rows[5]['b'],rows[5]['a'],rows[5]['s']),('X5','X5','유지'))
        gis=FakeApp(self.before,'gis',self.folder)
        with self.assertRaises(ValueError):gis.work_view_text()
        print('PASS without an after drawing the page still opens (after = field); temp drawing is refused')


class WorkEditTests(WorkViewTests):
    def test_edit_before_file_and_live_after(self):
        app=FakeApp(self.after,'after',self.folder);app.cable_k=self.k
        self.before.close()
        result=app.work_view_edit_core({'view':'before','cable':self.k,'n':5,'id':'X55','detail':'현장 수정'})
        self.assertTrue(result['ok']);self.assertEqual(result['where'],wf.SCENARIO_LABELS['before'])
        check=code['Store'](self.folder/'before.sqlite3')
        try:
            row=check.core(self.k,5);self.assertEqual((row['core_id'],row['detail']),('X55','현장 수정'))
            self.assertTrue(check.conn.execute('SELECT 1 FROM history_groups').fetchone(),'edit keeps undo history')
        finally:check.close()
        self.assertEqual(len(list((self.folder/'backup').glob('before_before_html_edit_*.sqlite3'))),1,'saved file backed up once')
        app.work_view_edit_core({'view':'before','cable':self.k,'n':6,'id':'X66','detail':''})
        self.assertEqual(len(list((self.folder/'backup').glob('before_before_html_edit_*.sqlite3'))),1)
        self.assertEqual(getattr(app,'saved',0),0,'editing the other file does not save the open drawing')
        rows={r['n']:r for r in result['scene']['cores'][self.k]}
        self.assertEqual((rows[5]['b'],rows[5]['a'],rows[5]['s']),('X55','X7','코어절체'))
        result=app.work_view_edit_core({'view':'after','cable':self.k,'n':10,'id':'X10','detail':''})
        self.assertEqual(self.after.core(self.k,10)['core_id'],'X10');self.assertEqual(app.saved,1,'the open drawing is saved after an edit')
        with self.assertRaises(ValueError):app.work_view_edit_core({'view':'during','cable':self.k,'n':1,'id':'Q'})
        with self.assertRaises(ValueError):app.work_view_edit_core({'view':'after','cable':'nope','n':1,'id':'Q'})
        with self.assertRaises(ValueError):app.work_view_edit_core({'view':'after','cable':self.k,'n':'x','id':'Q'})
        self.before=code['Store'](self.folder/'before.sqlite3')
        print('PASS HTML edit writes the field file (backup once, undo history) or the live after drawing, and refuses bad input')

    def test_cable_and_facility_edits(self):
        app=FakeApp(self.after,'after',self.folder);app.cable_k=self.k
        e=lambda **kw:app.work_view_edit(kw)
        r=e(op='cable_info',view='after',cable=self.k,status='절단',spec='24C',cable_id='K-NEW',lot='L9')
        c=self.after.cable(self.k)
        self.assertEqual((c['status'],c['spec'],c['size'],c['cable_id']),('절단','24C',24,'K-NEW'))
        self.assertEqual(code['cable_lot_no'](c),'L9');self.assertEqual(len(self.after.cores(self.k)),24)
        roles={x['id']:x['role'] for x in r['scene']['cables']};self.assertEqual(roles[self.k],'절단')
        r=e(op='node_add',view='during',name='새 함체',type='hamche',x=600.4,y=50)
        nid=r['result'];n=self.after.node(nid)
        self.assertEqual((n['name'],n['x'],n['y'],n['status']),('새 함체',600,50,'신설'))
        r=e(op='cable_add',view='after',a=self.nc,b=nid,status='신설',spec='48C',cable_id='',lot='')
        new=self.after.cable(r['result']);self.assertEqual((new['status'],new['size']),('신설',48))
        self.assertTrue(new['cable_id'],'신설 gets an automatic NEW id')
        e(op='node_move',view='after',node=nid,x=720,y=10)
        self.assertEqual((self.after.node(nid)['x'],self.after.node(nid)['y']),(720,40))
        e(op='node_info',view='after',node=nid,name='새 함체2',status='기설')
        self.assertEqual((self.after.node(nid)['name'],self.after.node(nid)['status']),('새 함체2','기설'))
        e(op='delete',view='after',kind='node',id=nid)
        self.assertIsNone(self.after.node(nid));self.assertIsNone(self.after.cable(new['id']),'cables of a deleted facility go too')
        e(op='delete',view='after',kind='cable',id=self.s);self.assertIsNone(self.after.cable(self.s))
        self.before.close()
        e(op='cable_info',view='before',cable=self.r,status='철거',spec='12C',cable_id='R',lot='BL')
        check=code['Store'](self.folder/'before.sqlite3')
        try:self.assertEqual(code['cable_lot_no'](check.cable(self.r)),'BL')
        finally:check.close()
        self.before=code['Store'](self.folder/'before.sqlite3')
        for bad in (dict(op='cable_info',view='after',cable=self.k,status='이상',spec='12C'),dict(op='cable_info',view='after',cable=self.k,status='기설',spec='abc'),
                    dict(op='cable_info',view='after',cable='nope',status='기설',spec='12C'),dict(op='node_add',view='after',name='',type='hamche',x=1,y=1),
                    dict(op='cable_add',view='after',a=self.na,b=self.na,status='신설',spec='12C'),dict(op='drop',view='after'),dict(op='delete',view='xx',kind='cable',id=self.k)):
            with self.assertRaises(ValueError):app.work_view_edit(bad)
        undo=self.after.undo();self.assertTrue(undo,'HTML edits are undoable in the program')
        print('PASS HTML cable/facility edits: info, add, move, rename, delete, bad input refused, undo works')

    def test_splices_and_paste(self):
        app=FakeApp(self.after,'after',self.folder);app.cable_k=self.k
        e=lambda **kw:app.work_view_edit(kw)
        t=self.after.add_cable(self.nb,self.nc,'T','12C','기설')
        r=e(op='core_paste',view='after',cable=t,start=1,lines=[['R1','첫줄'],['R9',''],[''],['X1']])
        self.assertIn('4줄 저장',r['result'])
        self.assertEqual([self.after.core(t,i)['core_id'] for i in (1,2,3,4)],['R1','R9','','X1'])
        self.assertEqual(self.after.core(t,1)['detail'],'첫줄')
        r=e(op='splice_add',view='after',node=self.nc,a_cable=self.s,a_n=1,b_cable=t,b_n=1,temporary=False)
        self.assertTrue(self.after.splice_for(self.nc,self.s,1))
        rows=r['scene']['splices']['after'][self.nc]
        self.assertIn([min(self.s,t),1,max(self.s,t),1,'R1'],[x[:5] for x in rows])
        with self.assertRaises(ValueError):e(op='splice_add',view='after',node=self.nc,a_cable=self.s,a_n=1,b_cable=t,b_n=2)
        with self.assertRaises(ValueError):e(op='splice_add',view='after',node=self.na,a_cable=self.s,a_n=1,b_cable=t,b_n=2)
        e(op='splice_del',view='after',node=self.nc,cable=self.s,n=1);self.assertFalse(self.after.splice_for(self.nc,self.s,1))
        with self.assertRaises(ValueError):e(op='splice_del',view='after',node=self.nc,cable=self.s,n=1)
        put(self.after,self.s,2,'Z2');put(self.after,t,2,'Z2')
        r=e(op='splice_range',view='after',node=self.nc,left=self.s,right=t,start=2,end=3)
        self.assertTrue(self.after.splice_for(self.nc,self.s,2));self.assertIn('직결',r['result'])
        with self.assertRaises(ValueError):e(op='core_paste',view='after',cable=t,start=1,lines=[])
        print('PASS HTML splices (connect, refuse wrong facility/occupied, disconnect, range) and multi-line paste')

    def test_phase_lock_and_switch(self):
        app=FakeApp(self.after,'after',self.folder);app.cable_k=self.k
        e=lambda **kw:app.work_view_edit(kw)
        r=e(op='phase_add',view='before',name='4차작업')
        self.assertEqual(r['where'],'후도면','phases always go to the open drawing')
        self.assertEqual(r['scene']['phase']['names'],['1차작업','2차작업','3차작업','4차작업'])
        with self.assertRaises(ValueError):e(op='phase_add',view='after',name='4차작업')
        with self.assertRaises(ValueError):e(op='phase_add',view='after',name=' ')
        r=e(op='cable_phase',view='before',cable=self.k,name='1차작업')
        self.assertEqual(r['scene']['phase']['cable'],{self.k:'1차작업'})
        self.assertEqual(wf.cable_phase_name(self.after,self.k),'1차작업')
        r=e(op='core_phase',view='during',ids=['X5'],name='2차작업')
        self.assertEqual(r['scene']['phase']['core'],{'X5':'2차작업'})
        self.assertEqual(wf.core_phase_source(self.after,'X5'),('core',['2차작업']))
        r=e(op='core_phase',view='after',ids=['X5'],name='')
        self.assertEqual(r['scene']['phase']['core'],{},'empty name follows the cable again')
        r=e(op='cable_phase',view='after',cable=self.k,name='');self.assertEqual(r['scene']['phase']['cable'],{})
        for bad in (dict(op='cable_phase',view='after',cable=self.k,name='9차'),dict(op='cable_phase',view='after',cable='nope',name='1차작업'),
                    dict(op='core_phase',view='after',ids=[],name='1차작업')):
            with self.assertRaises(ValueError):app.work_view_edit(bad)
        r=e(op='node_lock',view='after',node=self.nb,locked=True)
        self.assertTrue(wf.node_locked(self.after,self.nb))
        node={n['id']:n for n in r['scene']['nodes']}[self.nb]
        self.assertTrue(node['edit']['after']['locked']);self.assertFalse(node['edit']['before']['locked'])
        e(op='node_lock',view='after',node=self.nb,locked=False);self.assertFalse(wf.node_locked(self.after,self.nb))
        rn=self.after.add_node('RN1',50,50,'rn')
        with self.assertRaises(ValueError):e(op='node_lock',view='after',node=rn,locked=True)
        self.before.close()
        try:
            r=e(op='all_lock',view='before',locked=True)
            self.assertEqual(r['scene']['locks'],{'before':True,'after':False})
            self.assertIn('현장반영',r['where'])
        finally:self.before=code['Store'](self.folder/'before.sqlite3')
        self.assertTrue(self.before.all_enclosures_locked())
        with self.assertRaises(ValueError):app.work_view_switch({'kind':'gis'})
        self.assertEqual(app.work_view_switch({'kind':'after'}),{'ok':True,'started':False,'kind':'after'})
        r=app.work_view_switch({'kind':'before'});self.assertTrue(r['started'] and '현장반영' in r['label'])
        self.assertEqual(app.shown,1);app.later[-1]();self.assertEqual(app.switched,'before')
        page=app.work_view_text(live='T')
        for name in ('function phaseRow','function toggleAllLock','function switchKind','data-lock'):self.assertIn(name,page)
        print('PASS HTML work phases (open drawing only), facility lock / all lock per view, drawing switch')

    def test_trace_and_work_list(self):
        app=FakeApp(self.after,'after',self.folder);app.cable_k=self.k
        self.before.close()
        try:
            r=app.work_view_trace({'view':'after','id':'R1'})['value']
            self.assertTrue(r['found']);self.assertIn(self.s,r['cables']);self.assertTrue(r['groups'] and r['groups'][0]['paths'][0][0]['cable_id'])
            b=app.work_view_trace({'view':'before','id':'R2'})['value']
            self.assertTrue(b['found']);self.assertEqual(b['cables'],[self.r],'작업전 traces the saved field file')
            self.assertFalse(app.work_view_trace({'view':'after','id':'NOPE'})['value']['found'])
            with self.assertRaises(ValueError):app.work_view_trace({'view':'after','id':' '})
        finally:self.before=code['Store'](self.folder/'before.sqlite3')
        data=embedded(app.work_view_text(live='T'))
        self.assertEqual(data['work'][0]['id'],'X5');self.assertEqual(data['work'][0]['method'],'코어절체')
        self.assertIn('function runTrace',app.work_view_text(live='T'))
        print('PASS HTML core trace per view (live after / saved field file) and work list rows')

    def test_server_routes_token_and_host(self):
        import threading,urllib.request,urllib.error
        calls=[];ui=threading.get_ident()
        def core(payload):
            assert threading.get_ident()==ui,'routes must run on the UI thread';calls.append(payload)
            if payload.get('n')==99:raise ValueError('no slot')
            return {'ok':True,'scene':{'x':1}}
        server=wf.WorkViewServer({'page':lambda:'<html>page</html>','scene':lambda:{'n':1},'core':core})
        stop=threading.Event()
        def request(path,body=None,token=None,host=None):
            req=urllib.request.Request(f'http://127.0.0.1:{server.port}{path}',data=None if body is None else json.dumps(body).encode(),method='GET' if body is None else 'POST')
            if token:req.add_header('X-Telecom-Token',token)
            if host:req.add_header('Host',host)
            try:
                with urllib.request.urlopen(req,timeout=20) as r:return r.status,r.read().decode()
            except urllib.error.HTTPError as e:return e.code,e.read().decode()
        results={}
        def client():
            try:
                results['page']=request('/?t='+server.token)
                results['nopage']=request('/?t=wrong')
                results['scene']=request('/api/scene',token=server.token)
                results['scene_no']=request('/api/scene')
                results['edit']=request('/api/core',{'n':1},token=server.token)
                results['edit_err']=request('/api/core',{'n':99},token=server.token)
                results['edit_no']=request('/api/core',{'n':2})
                results['host']=request('/api/core',{'n':3},token=server.token,host='evil.example:80')
                results['unknown']=request('/api/drop',{'n':4},token=server.token)
            finally:stop.set()
        t=threading.Thread(target=client);t.start()
        import time
        while not stop.is_set():server.pump();time.sleep(.01)
        t.join();server.close()
        self.assertEqual(results['page'],(200,'<html>page</html>'))
        self.assertEqual(results['nopage'][0],403)
        self.assertEqual(results['scene'][0],200);self.assertEqual(json.loads(results['scene'][1]),{'ok':True,'value':{'n':1}})
        self.assertEqual(results['scene_no'][0],403);self.assertEqual(results['edit_no'][0],403);self.assertEqual(results['host'][0],403)
        self.assertEqual(results['unknown'][0],404)
        self.assertEqual(json.loads(results['edit'][1]),{'ok':True,'scene':{'x':1}})
        self.assertEqual(json.loads(results['edit_err'][1]),{'ok':False,'error':'no slot'})
        self.assertEqual([c['n'] for c in calls],[1,99],'only token + local-host requests reach the program')
        self.assertTrue(server.closed)
        print('PASS local edit server: token, host check, UI-thread routes, errors returned as messages')

    def test_live_page_has_token_and_edit_ui(self):
        app=FakeApp(self.after,'after',self.folder);app.cable_k=self.k
        data=embedded(app.work_view_text(live='TOKEN123'))
        self.assertTrue(data['meta']['live']);self.assertEqual(data['meta']['token'],'TOKEN123')
        cables={c['id']:c for c in data['cables']}
        self.assertEqual((cables[self.k]['in_before'],cables[self.k]['in_after']),(True,True))
        self.assertEqual((cables[self.s]['in_before'],cables[self.s]['in_after']),(False,True))
        text=app.work_view_text(live='TOKEN123')
        self.assertIn("'X-Telecom-Token'",text);self.assertIn('function editBox',text)
        print('PASS live page carries its token and the per-slot edit box')


def windows_ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    import faulthandler
    faulthandler.dump_traceback_later(180,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store;a=s.add_node('WV A',380,220);b=s.add_node('WV B',900,220)
            k=s.add_cable(a,b,'K','12C','기설');s.update_core(k,1,('WV-1','','normal','','on'))
            app.set_scenario_kind('before');app.refresh();app.update()
            assert app.work_view_button.winfo_ismapped()
            app.save_current_drawing(silent=True)
            opened=[]
            with patch.object(code['webbrowser'],'open',lambda url:opened.append(url)):url=app.open_work_view()
            assert url and url.startswith('http://127.0.0.1:') and opened==[url],(url,opened)
            import threading,urllib.request,time
            token=url.split('t=',1)[1];port=url.split(':')[2].split('/')[0];box={}
            def client():
                try:
                    with urllib.request.urlopen(url,timeout=60) as r:box['page']=r.read().decode('utf-8')
                    req=urllib.request.Request(f'http://127.0.0.1:{port}/api/core',data=json.dumps({'view':'before','cable':k,'n':1,'id':'WV-9','detail':'웹'}).encode(),method='POST')
                    req.add_header('X-Telecom-Token',token);req.add_header('Content-Type','application/json')
                    with urllib.request.urlopen(req,timeout=60) as r:box['edit']=json.loads(r.read().decode('utf-8'))
                except Exception as error:box['error']=repr(error)
            t=threading.Thread(target=client);t.start();deadline=time.time()+90
            while t.is_alive() and time.time()<deadline:app.update();time.sleep(.02)
            t.join(1);assert 'error' not in box and 'edit' in box,box.get('error')
            data=embedded(box['page'])
            assert data['meta']['live'] and data['meta']['token']==token
            assert [c['id'] for c in data['cables']]==[k] and data['cores'][k][0]['b']=='WV-1',data['cores'][k][:1]
            assert box['edit']['ok'],box['edit']
            assert s.core(k,1)['core_id']=='WV-9' and s.core(k,1)['detail']=='웹'
            assert box['edit']['scene']['cores'][k][0]['b']=='WV-9'
            labels_menu=[app.file_menu.entrycget(i,'label') for i in range(app.file_menu.index('end')+1)]
            assert '작업도면 전·중·후 (HTML)' in labels_menu,labels_menu
            assert '시작할 때 HTML 작업도면 열기' in labels_menu,labels_menu
            assert code['AUTO_HTML_ON_START'] is False,'checks never auto-open the browser'
            assert app.work_view_start_enabled() is True
            app.set_work_view_start(False);assert app.work_view_start_enabled() is False and app.work_view_start_var.get() is False
            app.set_work_view_start(True)
            with patch.object(code['webbrowser'],'open',lambda url:opened.append(url)):
                again=app.auto_open_work_view();assert again==url,(again,url)
                assert app.auto_open_work_view() is None,'auto open runs once'
            assert app.work_view_show_app()=={'ok':True}
            assert app.work_view_switch({'kind':'before'})['started'] is False,'already open'
            assert any(r['id']=='work_view' for r in app.drawing_tool_catalog())
            assert not errors,errors
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows work drawing button opens the live page, HTML edits change the open drawing, start-up option works')


if __name__=='__main__':
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(WorkViewTests),unittest.defaultTestLoader.loadTestsFromTestCase(WorkEditTests)])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
