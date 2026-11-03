"""V200/V202 (user): the drawing dashboard shows 작업코어현황 - every core on a
절단/철거 cable or at a 철거 함체/RN - instead of all signal cores.
도면현황 stays available with one button."""
import os
import sys
import tempfile
import unittest

from check_after_plan import wf,LocalApp,update


class WorkCoreStatus(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);s=self.s=self.app.store
        o=s.add_node('국사',0,0,'sub');a=s.add_node('A',100,0);b=s.add_node('B',200,0);m=s.add_node('MDF',300,0,'sub')
        self.rn=s.add_node('RN1',100,100,'rn');z=s.add_node('Z',300,100,'sub')
        self.c1=s.add_cable(o,a,'C1','12C','기설');self.cut=s.add_cable(a,b,'CUT','12C','기설');self.c3=s.add_cable(b,m,'C3','12C','기설')
        self.rc=s.add_cable(a,self.rn,'RC','12C','기설');self.other=s.add_cable(b,z,'OTHER','12C','기설')
        for c in (self.c1,self.cut,self.c3):update(s,c,1,dict(core_id='11',detail='d',signal='on'))
        update(s,self.c1,2,dict(core_id='22',detail='d',signal='on'));update(s,self.rc,2,dict(core_id='22',detail='d',signal='on'))
        update(s,self.c1,3,dict(core_id='33',detail='d',signal='on'));update(s,self.other,3,dict(core_id='33',detail='d',signal='on'))
        update(s,self.cut,5,dict(core_id='55',detail='d',signal='off'))
        s.connect(a,(self.c1,1),(self.cut,1));s.connect(b,(self.cut,1),(self.c3,1));s.connect(a,(self.c1,2),(self.rc,2))
        s.conn.commit()

    def tearDown(self):self.s.close();self.temp.cleanup()

    def test_no_marks(self):
        work=wf.work_core_report(self.s)
        self.assertEqual((work['total'],work['work_cables'],work['removed_nodes']),(0,0,0),work)
        print('PASS no cut/removed marks means no work cores')

    def test_cut_cable_and_removed_rn(self):
        s=self.s
        s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(self.cut,))
        s.conn.execute("UPDATE nodes SET status='철거' WHERE id=?",(self.rn,));s.conn.commit()
        work=wf.work_core_report(s)
        ids={r['core_id'] for r in work['rows']}
        # 11 rides the cut cable, 22 reaches the removed RN; 33 is untouched;
        # 55 is OFF on the cut cable and only counted as excluded.
        self.assertEqual(ids,{'11','22'},work)
        self.assertEqual(work['excluded'],1,work)
        self.assertEqual((work['cut_cables'],work['removed_cables'],work['removed_nodes']),(1,0,1))
        overall=wf.completion_report(s)
        self.assertGreater(overall['total'],work['total'])
        self.assertLessEqual(work['done'],work['total'])
        print('PASS work cores = cores on cut cable and removed RN only')

    def mark_before(self):
        s=self.s
        s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(self.cut,))
        s.conn.execute("UPDATE nodes SET status='철거' WHERE id=?",(self.rn,));s.conn.commit()
        s.backup_to(self.app.scenario_path('before'))

    def test_matches_work_list_after(self):
        # V202 (user: dashboard 35 but 작업필요코어(전체) 49): the dashboard
        # counts exactly the work list rows, OFF cores included in 작업코어.
        self.mark_before()
        work=wf.Workflow(self.app).report()
        ids={r['core_id'] for r in work['rows']}
        self.assertEqual(ids,{'11','22','55'},ids)
        result=wf.work_core_list_report(self.s,work)
        self.assertEqual(result['all'],len(work['rows']))
        self.assertEqual(result['total']+result['excluded'],result['all'])
        self.assertEqual(result['cut'],2,result)
        print('PASS after dashboard work cores equal the work list rows')

    def test_matches_work_list_before(self):
        self.mark_before();self.app.scenario_kind=lambda:'before'
        self.s.conn.execute("UPDATE meta SET value='before' WHERE key='active_scenario'");self.s.conn.commit()
        work=wf.Workflow(self.app).report()
        self.assertEqual({r['core_id'] for r in work['rows']},{'11','22','55'})
        result=wf.work_core_list_report(self.s,work)
        self.assertEqual(result['all'],3,result)
        # OFF 55 needs no connection: it stays a work core but leaves the rate.
        self.assertEqual((result['total'],result['excluded']),(2,1),result)
        print('PASS before dashboard work cores equal the work list, OFF set aside')

    def test_removed_cable(self):
        s=self.s;s.conn.execute("UPDATE cables SET status='철거' WHERE id=?",(self.other,));s.conn.commit()
        work=wf.work_core_report(s)
        self.assertEqual({r['core_id'] for r in work['rows']},{'33'})
        self.assertEqual(work['removed_cables'],1)
        print('PASS removed cable cores counted')


def check_ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):
        print('SKIP dashboard UI check (Windows only)');return
    import faulthandler
    from unittest.mock import patch
    from check_after_plan import code
    faulthandler.dump_traceback_later(120,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store;a=s.add_node('WK A',300,200);b=s.add_node('WK B',600,200,'sub');r=s.add_node('WK RN',300,400,'rn')
            c=s.add_cable(a,b,'WKC','12C','기설');d=s.add_cable(a,r,'WKD','12C','기설')
            s.update_core(c,1,('WK-1','d','normal','','on'));s.update_core(d,2,('WK-2','d','normal','','on'))
            s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(c,));s.conn.commit()
            app.refresh();app.update()
            assert app.dashboard_mode=='work',app.dashboard_mode
            assert app.dashboard_title_label.cget('text')=='작업코어 현황'
            rows=app.work_report()['rows']
            assert f'작업코어 {len(rows)}개' in app.work_progress_text.cget('text'),(app.work_progress_text.cget('text'),len(rows))
            app.toggle_dashboard_mode();app.update()
            assert app.dashboard_mode=='drawing' and app.dashboard_title_label.cget('text')=='도면 현황'
            assert '필수 코어' in app.work_progress_text.cget('text')
            assert '전체 2 ' in app.work_progress_completed.cget('text'),app.work_progress_completed.cget('text')
            app.toggle_metric_details();app.toggle_dashboard_mode();app.update()
            assert '작업코어' in app.work_progress_text.cget('text') and '작업필요코어(전체)' in app.work_progress_note.cget('text')
            assert not errors,errors
            print('PASS dashboard shows work cores and toggles to drawing status')
        finally:app.on_close()


if __name__=='__main__':
    result=unittest.main(exit=False,verbosity=0).result
    if not result.wasSuccessful():
        print('::error::check_work_core_status failed');sys.exit(1)
    try:check_ui()
    except Exception as error:
        print('::error::check_work_core_status UI failed: '+type(error).__name__);raise
