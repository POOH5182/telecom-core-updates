"""Production planning engine, transactional renumbering and real Windows UI gate."""
import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
code=runpy.run_path(str(ROOT/'app'/'telecom_core_app.pyw'),run_name='planner_check')
ns=code['App'].__init__.__globals__;wf=ns['workflow']


def update(store,cable,index,values):
    row=dict(store.core(cable,index));row.update(values)
    store.update_core(cable,index,tuple(row[k] for k in wf.PLAN_FIELDS))


class LocalApp:
    def __init__(self,home):
        self.home=Path(home);self.store=code['Store'](self.home/'drawing.sqlite3');self.saved=False
        self.store.conn.execute("INSERT INTO meta VALUES('active_scenario','after')");self.store.conn.commit()
    def scenario_kind(self):return 'after'
    def scenario_path(self,kind):return self.home/(kind+'.sqlite3')
    def save_current_drawing(self,silent=False):self.store.backup_to(self.scenario_path('after'));self.saved=True


class PlannerTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name)
        self.store=self.app.store;self.service=wf.AfterPlanner(self.app)
        s=self.store
        self.a=s.add_node('시작 함체',0,0);self.h=s.add_node('접속 함체',100,0);self.b=s.add_node('끝 함체',200,0)
        self.big=s.add_cable(self.a,self.h,'BIG','12C','기설');self.small=s.add_cable(self.h,self.b,'SMALL','6C','기설')
        for cid,l,r in (('ID-A',1,2),('ID-B',2,1),('ID-C',3,4)):
            update(s,self.big,l,{'core_id':cid,'detail':cid+' 내역','signal':'off'})
            s.connect(self.h,(self.big,l),(self.small,r))
            update(s,self.big,l,{'signal':'off'})
        s.backup_to(self.app.scenario_path('before'))
    def tearDown(self):self.store.close();self.temp.cleanup()
    def row(self,cid):return next(r for r in self.service.report()['rows'] if r['core_id']==cid)

    def test_whole_network_and_changes(self):
        report=self.service.report()
        self.assertEqual((report['total'],report['done']),(3,3));self.assertTrue(report['ready'])
        # No removed cable exists: the old limited report would have zero required cores.
        self.assertEqual(self.store._work_required_from_connection(self.store.conn),[])
        update(self.store,self.big,5,{'core_id':'NEW','detail':'신규','signal':'off'})
        row=self.row('NEW');self.assertEqual(row['change'],'신규');self.assertFalse(row['complete'])
        self.assertTrue(any('미접속' in n for n in row['notes']))
        self.service.review(['NEW'],'신규 연결 계획 확인',self.service.report()['token'])
        self.assertFalse(self.row('NEW')['complete']) # acknowledgement cannot hide broken topology

    def test_renumber_annotations_edges_undo_redo_and_before(self):
        s=self.store
        wf.save_annotations(s,(self.small,2),['정상','확인필요'],'보존 메모 A')
        wf.save_annotations(s,(self.small,1),['정상'],'다른 메모 B')
        # Force consistent metadata across the whole ID, preserving off signals.
        before_file=self.app.scenario_path('before').read_bytes()
        original=wf.plan_snapshot(s.conn);p=self.service.preview()
        self.assertGreater(p['after'],p['before']);self.assertEqual(p['after'],3)
        self.assertTrue(all(cid==self.small for cid,idx in p['mapping']))
        self.assertEqual(wf.plan_snapshot(s.conn),original) # preview is read-only
        backup=self.service.apply(p);self.assertTrue(backup.exists())
        changed=wf.plan_snapshot(s.conn)
        self.assertEqual(s.core(self.small,1)['core_id'],'ID-A')
        self.assertEqual(s.core(self.small,2)['core_id'],'ID-B')
        self.assertEqual(s.core(self.small,3)['core_id'],'ID-C')
        self.assertEqual(s.core(self.small,1)['signal'],'off')
        self.assertEqual(original['core_annotations'],changed['core_annotations'])
        self.assertEqual(self.app.scenario_path('before').read_bytes(),before_file)
        self.assertTrue(all(self.row(cid)['after']['result']['complete'] for cid in ('ID-A','ID-B','ID-C')))
        s.undo();self.assertEqual(wf.plan_snapshot(s.conn),original)
        s.redo();self.assertEqual(wf.plan_snapshot(s.conn),changed)
        s.close();self.app.store=code['Store'](s.path);self.store=self.app.store
        self.assertEqual(wf.plan_snapshot(self.store.conn),changed)

    def test_fixed_empty_and_id_and_enclosure(self):
        self.service.set_fixed(slots=[(self.small,3)],reason='예비 번호')
        self.service.set_fixed(core_ids=['ID-A'],reason='서비스 선번 고정')
        p=self.service.preview();self.assertNotIn((self.small,2),p['mapping'])
        self.assertNotIn((self.small,3),p['mapping'])
        self.assertTrue(p['unmatched'])
        self.store.conn.execute('UPDATE nodes SET extra_json=? WHERE id=?',(json.dumps({'editLocked':True}),self.b));self.store.conn.commit()
        self.assertFalse(self.service.preview()['mapping'])

    def test_capacity_plans_and_retired_missing(self):
        self.service.set_fixed(slots=[(self.small,i) for i in (3,5,6)],reason='예비')
        self.service.save_plan('NEW','연결 필요',[self.small],[],'','증설 예정')
        r=self.service.report();self.assertTrue(any('부족' in x for x in r['issues']))
        self.assertTrue(any('계획한' in x for x in self.row('NEW')['notes']))
        with self.store.action('시험 삭제'):
            self.store.conn.execute("DELETE FROM splices WHERE core1_index=3 OR core2_index=4")
            self.store.conn.execute("UPDATE cores SET core_id='',detail='',signal='' WHERE core_id='ID-C'")
        self.assertIn('누락',self.row('ID-C')['change'])
        self.service.save_plan('ID-C','폐지 예정',[],[],'계획 폐지','')
        self.service.review(['ID-C'],'폐지 후 잔존 없음',self.service.report()['token'])
        self.assertTrue(self.row('ID-C')['complete'])
        self.service.save_plan('ID-A','폐지 예정',[],[],'폐지 계획','')
        self.service.review(['ID-A'],'폐지 확인',self.service.report()['token'])
        self.assertFalse(self.row('ID-A')['complete'])

    def test_exception_separate_from_signal_and_review_stales(self):
        update(self.store,self.big,5,{'core_id':'EX','detail':'예외','status1':'exception'})
        row=self.row('EX');self.assertTrue(row['exception']);self.assertEqual(row['status'],'예외 확인')
        self.service.review(['EX'],'미사용 인입 예외 확인',self.service.report()['token'])
        self.assertEqual(self.row('EX')['status'],'예외 확인 완료')
        update(self.store,self.big,5,{'detail':'변경된 예외 내역'})
        self.assertFalse(self.row('EX')['complete'])
        update(self.store,self.big,6,{'core_id':'SIG','signal':'exception'})
        self.assertFalse(self.row('SIG')['exception']);self.assertFalse(self.row('SIG')['complete'])

    def test_rn_ports_preserved(self):
        s=self.store;rn=s.add_node('RN',300,0,'rn');c=s.add_cable(self.b,rn,'RN-C','6C','기설')
        s.connect(self.b,(self.small,2),(c,3));s.connect(rn,(c,3),('PORT:'+rn,1))
        # Existing B/C terminate at b, which now has two cables; explicitly mark b terminal.
        s.conn.execute('UPDATE nodes SET extra_json=? WHERE id=?',(json.dumps({'terminal':True}),self.b));s.conn.commit()
        ports=[dict(r) for r in s.conn.execute('SELECT * FROM ports')]
        p=self.service.preview();self.service.apply(p)
        self.assertEqual(ports,[dict(r) for r in s.conn.execute('SELECT * FROM ports')])
        self.assertEqual(s.core('PORT:'+rn,1)['core_id'],'ID-A')

    def test_stale_guard_and_atomic_rollback(self):
        p=self.service.preview();self.service.set_fixed(slots=[(self.small,6)],reason='예약')
        with self.assertRaisesRegex(ValueError,'변경'):self.service.apply(p)
        p=self.service.preview();original=wf.plan_snapshot(self.store.conn)
        self.store.conn.execute("CREATE TRIGGER test_fail BEFORE UPDATE ON cores WHEN NEW.core_id='ID-C' BEGIN SELECT RAISE(ABORT,'test interruption'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.service.apply(p)
        self.assertEqual(wf.plan_snapshot(self.store.conn),original)

    def test_pending_connections_and_bad_splices(self):
        self.store.disconnect(self.h,self.small,2)
        row=self.row('ID-A');self.assertFalse(row['complete']);self.assertTrue(any('끊어짐' in x for x in row['notes']))
        self.assertNotIn((self.small,2),self.service.preview()['mapping'])
        with self.store.action('잘못된 접속 시험'):
            self.store.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(self.a,self.big,1,self.small,2))
        self.assertTrue(self.service.report()['issues'])
        with self.assertRaisesRegex(ValueError,'접속'):self.service.preview()

    def test_stage_invalidation_final_save_and_orders(self):
        r=self.service.report()
        with self.assertRaises(ValueError):self.service.final_check(r['token'])
        for name in wf.PLAN_STAGES:self.service.mark_stage(name,self.service.report()['token'])
        self.service.final_check(self.service.report()['token']);self.assertTrue(self.app.saved)
        self.assertTrue(self.service.report()['final'])
        self.service.apply(self.service.preview())
        self.assertFalse(any(self.service.report()['stages']));self.assertFalse(self.service.report()['final'])
        orders=self.service.work_orders();self.assertTrue(any(r[2]=='해체' for r in orders));self.assertTrue(any(r[2]=='접속' for r in orders))
        self.assertTrue(all(r[0]=='접속 함체' for r in orders if r[2] in ('해체','접속')))
        r=self.service.report();self.service.review([x['core_id'] for x in r['rows']],'재배치 확인',r['token'])
        self.assertTrue(self.service.report()['ready'])

    def test_survey_and_assignment_references_move(self):
        s=self.store
        extra={'autoSameNumberExcluded':[f'{self.small}::4'],'assignmentExceptions':{f'{self.small}::4':True}}
        s.conn.execute('UPDATE nodes SET extra_json=? WHERE id=?',(json.dumps(extra),self.h))
        s.conn.execute('INSERT INTO survey_rows(id,node_id,left_cable,left_index,right_cable,right_index,invalid,error_message,created_at) VALUES(?,?,?,?,?,?,0,?,?)',('survey-1',self.h,self.big,3,self.small,4,'','test'));s.conn.commit()
        original=wf.plan_snapshot(s.conn);self.service.apply(self.service.preview())
        extra=json.loads(s.node(self.h)['extra_json']);self.assertIn(f'{self.small}::3',extra['autoSameNumberExcluded'])
        self.assertIn(f'{self.small}::3',extra['assignmentExceptions'])
        self.assertEqual(s.conn.execute('SELECT right_index FROM survey_rows').fetchone()[0],3)
        s.undo();self.assertEqual(wf.plan_snapshot(s.conn),original)

    def test_export_csv(self):
        path=Path(self.temp.name)/'work.csv'
        wf.plan_export_csv(path,['코어ID','내역'],[['=1+2','한글\n두 줄'],['00012','OFF']])
        raw=path.read_bytes();self.assertTrue(raw.startswith(b'\xef\xbb\xbf'));self.assertIn("'=1+2",raw.decode('utf-8-sig'))


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))):
            app=code['App']();app.withdraw();app.report_callback_exception=lambda *args:errors.append(str(args))
            a=app.store.add_node('검증 A',0,0);h=app.store.add_node('검증 접속',100,0);b=app.store.add_node('검증 B',200,0)
            big=app.store.add_cable(a,h,'BIG','12C','기설');small=app.store.add_cable(h,b,'SMALL','6C','기설')
            update(app.store,big,1,{'core_id':'GUI-1','detail':'UI 검증'});app.store.connect(h,(big,1),(small,2))
            app.save_current_drawing(silent=True)
            with patch.object(code['messagebox'],'askyesno',return_value=True):app.load_scenario('after')
            dialog=wf.AfterPlanDialog(app);app.update()
            assert len(dialog.tabs.tabs())==6
            assert dialog.report['total']==1
            for tab in dialog.tabs.tabs():dialog.tabs.select(tab);app.update()
            dialog.tables['compare'].selection_set('0');dialog.show_detail('compare')
            editor=wf.PlanEditor(dialog,dialog.visible[0]);app.update();editor.note.insert('end',' 작업표 메모');editor.save();app.update()
            route=wf.PlanRouteDialog(dialog,dialog.visible[0],dialog.report['old'],dialog.report['net']);app.update();route.destroy()
            dialog.calculate();app.update();assert dialog.proposal['after']==1
            with patch.object(code['messagebox'],'askyesno',return_value=True),patch.object(code['messagebox'],'showinfo'):
                dialog.apply()
            app.update();assert app.store.core(small,1)['core_id']=='GUI-1'
            dialog.destroy();app.update();app.on_close()
            assert not errors,errors
    print('PASS Windows after workbench tabs, plan editor, route drawing, preview and explicit apply')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PlannerTest))
    if not result.wasSuccessful():sys.exit(1)
    windows_ui()
    print('PASS full-network checks, fixed capacity, preview, metadata/ports/topology, atomic rollback, undo/redo, stage invalidation and CSV')
