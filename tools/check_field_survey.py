"""Real field observations, atomic rewiring and GIS/field/cloud preservation gates."""
import os
from legacy_field_fixture import existing_field
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
code=runpy.run_path(str(ROOT/'app'/'telecom_core_app.pyw'),run_name='field_check')
wf=code['App'].__init__.__globals__['workflow']


class FieldTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.store=code['Store'](self.home/'field.sqlite3');s=self.store
        s.conn.execute("INSERT INTO meta VALUES('active_scenario','before')");s.conn.commit()
        self.a=s.add_node('A 끝단',0,0);self.h=s.add_node('조사 함체',240,0)
        self.b=s.add_node('B 끝단',480,0);self.c=s.add_node('C 끝단',240,240)
        self.left=s.add_cable(self.a,self.h,'A','6C','기설')
        self.right=s.add_cable(self.h,self.b,'B','6C','기설')
        self.third=s.add_cable(self.h,self.c,'C','6C','기설')
        for index,cid in ((1,'LIVE-1'),(2,'LIVE-2'),(3,'LIVE-3')):
            s.update_core(self.left,index,(cid,cid+' 내역','normal','','off'))
            s.connect(self.h,(self.left,index),(self.right,index))
    def tearDown(self):self.store.close();self.temp.cleanup()
    def engine(self):return wf.FieldSurvey(self.store,self.h)
    def row(self,number):return next(r for r in self.engine().report() if r['row']==number)
    def snapshot(self):return wf.plan_snapshot(self.store.conn),wf.field_records(self.store)

    def test_compare_missing_and_identity_staleness(self):
        old=wf.plan_snapshot(self.store.conn)
        self.engine().save('A\tB\tC\n1\t1\t\n2\t\t2\n\t\t')
        self.assertEqual(wf.plan_snapshot(self.store.conn),old)
        self.assertEqual(self.row(2)['status'],'확인완료')
        self.assertEqual(self.row(3)['status'],'불일치')
        self.assertTrue(any(r['source']=='미조사' and (self.left,3) in r['slots'] for r in self.engine().report()))
        key=self.row(2)['key'];self.engine().mark({key},'미확인')
        self.assertEqual(self.row(2)['status'],'미확인')
        self.engine().mark({key},'확인');self.engine().mark({key},'이상','현장 판독 불가')
        self.assertEqual(self.row(2)['status'],'이상')
        self.engine().mark({key},'확인')
        with self.store.action('연결된 코어ID 변경'):
            self.store.conn.execute("UPDATE cores SET core_id='CHANGED' WHERE core_id='LIVE-1'")
        self.assertNotEqual(self.row(2)['status'],'확인완료')

    def test_validation_duplicate_range_and_empty_cells(self):
        self.engine().save('A\tB\tC\n1\t1\t\n1\t\t2\n999\t2\t\n3\t3\t')
        self.assertEqual(self.row(2)['status'],'이상');self.assertEqual(self.row(3)['status'],'이상')
        self.assertEqual(self.row(4)['status'],'이상');self.assertEqual(self.row(5)['status'],'확인완료')
        old=self.snapshot()
        with self.assertRaises(ValueError):wf.field_preview(self.store,self.h,{self.row(2)['key']})
        self.assertEqual(self.snapshot(),old)

    def test_apply_preview_backup_contract_undo_and_unrelated_links(self):
        self.engine().save('A\tB\tC\n1\t1\t\n2\t\t2')
        key=self.row(3)['key'];old=self.snapshot();groups=len(self.store.history_rows())
        preview=wf.field_preview(self.store,self.h,{key})
        self.assertEqual(self.snapshot(),old)
        self.assertTrue(any(r[0]=='기존 연결 해제' for r in preview['changes']))
        wf.field_apply(self.store,self.h,preview['keys'],preview['revision'],preview['generation'])
        self.assertEqual(self.row(3)['status'],'확인완료')
        self.assertIsNotNone(self.store.splice_for(self.h,self.left,3))
        self.assertEqual(self.store.core(self.third,2)['core_id'],'LIVE-2')
        self.assertEqual(len(self.store.history_rows()),groups+1)
        changed=self.snapshot();self.store.undo();self.assertEqual(self.snapshot(),old)
        self.store.redo();self.assertEqual(self.snapshot(),changed)
        self.assertTrue(any((self.right,2) in r['slots'] and r['status']=='미확인' for r in self.engine().report()))

    def test_conflict_all_or_nothing_locks_and_stale_preview(self):
        self.store.update_core(self.third,1,('OTHER','다른 서비스','normal','','on'))
        self.engine().save('A\tB\tC\n2\t\t2\n1\t\t1')
        keys={self.row(2)['key'],self.row(3)['key']};old=self.snapshot()
        with self.assertRaises(ValueError):
            wf.field_apply(self.store,self.h,keys,self.store.data_revision(),self.store._view_generation)
        self.assertEqual(self.snapshot(),old)
        key=self.row(2)['key'];p=wf.field_preview(self.store,self.h,{key})
        self.store.set_node_locked(self.h,True)
        with self.assertRaises(ValueError):wf.field_preview(self.store,self.h,{key})
        self.store.set_node_locked(self.h,False)
        with self.assertRaises(ValueError):wf.field_apply(self.store,self.h,p['keys'],p['revision'],p['generation'])

    def test_terminals_completeness_and_cloud_all_stages(self):
        self.engine().save('A\tB\tC\n1\t1\t\n2\t2\t\n3\t3\t')
        wf.FieldSurvey(self.store,self.a).save('A\n1\n2\n3')
        wf.FieldSurvey(self.store,self.b).save('B\n1\n2\n3')
        self.assertFalse(wf.field_check_rows(self.store))
        self.assertFalse([r for r in self.store.before_drawing_check_rows() if r['level']=='오류'])
        self.assertEqual(wf.field_summary(self.store,self.h)['done'],3)
        folder=self.home/'scenarios';folder.mkdir()
        for kind in ('gis','before','after'):self.store.backup_to(folder/(kind+'.sqlite3'))
        bundle=wf.cloud_bundle(self.store,folder);contents=wf.cloud_unpack(bundle)
        self.assertEqual(set(contents),{'working.sqlite3','gis.sqlite3','before.sqlite3','after.sqlite3'})
        restored=self.home/'restored.sqlite3';restored.write_bytes(contents['working.sqlite3'])
        other=code['Store'](restored)
        try:self.assertEqual(wf.field_records(other),wf.field_records(self.store))
        finally:other.close()


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp
        errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=True), \
             patch.object(code['messagebox'],'askyesno',return_value=True):
            app=code['App']();app.withdraw();app.report_callback_exception=lambda *args:errors.append(str(args))
            try:
                assert app.scenario_kind()=='gis'
                a=app.store.add_node('시작',0,0);h=app.store.add_node('함체',240,0);b=app.store.add_node('끝',480,0)
                left=app.store.add_cable(a,h,'L','6C','기설');right=app.store.add_cable(h,b,'R','6C','기설')
                app.store.connect(h,(left,1),(right,1),temporary=True)
                assert app.store.before_drawing_check_rows() # GIS has errors; copying is still allowed.
                assert (existing_field(app) or app.load_scenario('before'))
                gis=app.scenario_path('gis').read_bytes()
                assert app.scenario_kind()=='before'
                app.store.update_core(left,1,('FIELD-1','현장 확인','normal','','off'))
                app.store.update_core(right,1,('FIELD-1','현장 확인','normal','','off'))
                app.save_current_drawing(silent=True)
                assert app.scenario_path('gis').read_bytes()==gis
                assert app.load_scenario('gis');assert app.store.core(left,1)['core_id'].startswith('임시-')
                assert app.load_scenario('before');assert app.store.core(left,1)['core_id']=='FIELD-1'
                app.deiconify();app.update()
                node=code['NodeDialog'](app,app.store,h);node.field_survey_open();app.update()
                dialog=next(w for w in node.winfo_children() if isinstance(w,wf.FieldSurveyDialog))
                dialog.clipboard_clear();dialog.clipboard_append('L\tR\n1\t1');dialog.sheet.paste_from_a1()
                dialog.inspect();app.update()
                assert dialog.rows[0]['status']=='확인완료'
                assert app.store.node_warning_summary()[h]['field']['done']==1
                assert not [r for r in app.store.before_drawing_check_rows() if r['level']=='오류'] # Terminal enclosures no longer require field acknowledgement.
                dialog.destroy();node.destroy()
                wf.FieldSurvey(app.store,a).save('L\n1');wf.FieldSurvey(app.store,b).save('R\n1')
                assert not [r for r in app.store.before_drawing_check_rows() if r['level']=='오류'],app.store.before_drawing_check_rows()
                assert app.load_scenario('after');assert app.scenario_kind()=='after'
                assert app.scenario_path('gis').read_bytes()==gis
                assert all(kind in app.workflow_buttons for kind in ('gis','before','check','after','complete'))
                assert not errors,errors
            finally:app.on_close()
    print('PASS Windows GIS copy despite errors, independent field edits, three-stage switching, investigation UI, enclosure badges and field-to-after gate')


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(FieldTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS field comparison, terminal verification, pending/issue states, stale guards, conflict rollback, undo/redo and GIS/field/after cloud bundle')
