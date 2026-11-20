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
            before=s.conn.total_changes;opened=[]
            with patch.object(code['webbrowser'],'open',lambda url:opened.append(url)):path=app.open_work_view()
            assert path and path.exists() and opened and opened[0].startswith('file:'),(path,opened)
            assert s.conn.total_changes==before
            data=embedded(path.read_text(encoding='utf-8'))
            assert [c['id'] for c in data['cables']]==[k] and data['cores'][k][0]['b']=='WV-1',data['cores'][k][:1]
            labels_menu=[app.file_menu.entrycget(i,'label') for i in range(app.file_menu.index('end')+1)]
            assert '작업도면 전·중·후 (HTML)' in labels_menu,labels_menu
            assert any(r['id']=='work_view' for r in app.drawing_tool_catalog())
            assert not errors,errors
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows work drawing button writes the joined page without changing the drawing')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WorkViewTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
