"""Actual after allocation: replacement, constraints, atomicity and Windows UI."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_after_plan import code,wf,LocalApp,update
from check_after_routes import drawing


def converted(app,count=2):
    s=app.store
    nodes=[s.add_node(name,x,180) for name,x in (('끝 A',80),('함체 B',300),('함체 C',530),('끝 D',760))]
    cables=[s.add_cable(nodes[i],nodes[i+1],name,'36C','기설') for i,name in enumerate(('KEEP-L','REPLACE','KEEP-R'))]
    for index in range(1,count+1):
        middle=30-index
        update(s,cables[0],index,dict(core_id=f'CORE-{index}',detail=('TRUNK' if index==1 else 'FTTH')+f' 회선 {index}',signal='on' if index==1 else 'unknown'))
        s.connect(nodes[1],(cables[0],index),(cables[1],middle))
        s.connect(nodes[2],(cables[1],middle),(cables[2],index))
    s.backup_to(app.scenario_path('before'))
    with s.action('기설 케이블을 신설로 변경'):s.conn.execute("UPDATE cables SET status='신설' WHERE id=?",(cables[1],))
    return nodes,cables


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store
        self.nodes,self.cables=converted(self.app);self.service=wf.AfterAllocator(self.app)
    def tearDown(self):self.s.close();self.temp.cleanup()
    def snapshot(self):return wf.plan_snapshot(self.s.conn)
    def before(self):return self.app.scenario_path('before').read_bytes()
    def preview(self,**options):return self.service.preview({**wf.ALLOCATION_DEFAULTS,**options})
    def entries(self,p):return {r['core_id']:r for r in p['results']}

    def test_converted_cable_moves_metadata_and_splices_preserves_endpoints_and_undo(self):
        wf.save_annotations(self.s,(self.cables[0],1),['정상'],'입력 메모 보존 시험')
        physical=self.snapshot();state=wf.state(self.s);history=self.s.history_rows();before=self.before()
        p=self.preview();self.assertTrue(p['actions']);self.assertEqual(self.snapshot(),physical)
        self.assertEqual((wf.state(self.s),self.s.history_rows(),self.before()),(state,history,before))
        self.assertEqual(self.entries(p)['CORE-1']['numbers'],[1,1,1]);self.assertEqual(self.entries(p)['CORE-2']['numbers'],[2,2,2])
        backup=self.service.apply(p);self.assertTrue(backup.exists())
        self.assertEqual(self.s.core(self.cables[1],1)['core_id'],'CORE-1');self.assertEqual(self.s.core(self.cables[1],2)['core_id'],'CORE-2')
        after=self.snapshot();self.assertEqual(after['core_annotations'],physical['core_annotations']);self.assertEqual(after['ports'],physical['ports'])
        for cid in (self.cables[0],self.cables[2]):self.assertEqual([r for r in physical['cores'] if r['cable_id']==cid],[r for r in after['cores'] if r['cable_id']==cid])
        self.assertEqual(wf.completion_report(self.s)['rate'],100);self.assertTrue(wf.AfterRoutePlanner(self.app).summary()['ready'])
        self.assertEqual(self.before(),before);self.s.undo();self.assertEqual(self.snapshot(),physical);self.assertEqual(wf.state(self.s),state)
        self.s.redo();self.assertEqual(self.snapshot(),after)

    def test_deleted_original_cables_restore_all_before_identities(self):
        original=self.before()
        with self.s.action('기존 케이블 삭제'):
            self.s.conn.execute('DELETE FROM splices');self.s.conn.execute('DELETE FROM cores');self.s.conn.execute('DELETE FROM cables')
        fresh=[self.s.add_cable(self.nodes[i],self.nodes[i+1],'FRESH-'+str(i),'12C','신설') for i in range(3)]
        p=self.preview();self.assertEqual(set(self.entries(p)),{'CORE-1','CORE-2'})
        self.assertTrue(all(r['status']=='배분 가능' for r in p['results']),p['results'])
        self.service.apply(p)
        for cid in fresh:self.assertEqual({r['core_id'] for r in self.s.cores(cid) if r['core_id']},{'CORE-1','CORE-2'})
        self.assertEqual(wf.completion_report(self.s)['rate'],100);self.assertEqual(self.before(),original)

    def test_deleted_middle_and_cut_original_are_both_supported(self):
        with self.s.action('중간 케이블 삭제'):
            middle=self.cables[1];self.s.conn.execute('DELETE FROM splices WHERE cable1_id=? OR cable2_id=?',(middle,middle))
            self.s.conn.execute('DELETE FROM cores WHERE cable_id=?',(middle,));self.s.conn.execute('DELETE FROM cables WHERE id=?',(middle,))
        fresh=self.s.add_cable(self.nodes[1],self.nodes[2],'NEW-MIDDLE','12C','신설')
        self.service.apply(self.preview());self.assertEqual(wf.completion_report(self.s)['rate'],100)
        self.assertEqual(self.s.core(fresh,1)['core_id'],'CORE-1')
        with tempfile.TemporaryDirectory() as d:
            app=LocalApp(d);drawing(app);service=wf.AfterAllocator(app);p=service.preview()
            self.assertEqual(sum(r[0]=='철거 접속 해체' for r in p['actions']),2)
            service.apply(p);self.assertEqual(wf.completion_report(app.store)['rate'],100);app.store.close()

    def test_rules_reservations_constrained_matching_and_capacity_failure_preserve_data(self):
        # A flexible earlier core must not steal CORE-2's only allowed number.
        p=self.preview(ranges='FTTH=1',reserved='3-12',reserve_tail=24)
        self.assertEqual(self.entries(p)['CORE-2']['numbers'][1],1)
        self.assertEqual(self.entries(p)['CORE-1']['numbers'][1],2)
        self.service.apply(p);self.assertEqual(wf.completion_report(self.s)['rate'],100)
        self.s.undo();original=self.snapshot()
        p=self.preview(reserved='1-35')
        held=[r for r in p['results'] if r['status']=='보류'];self.assertTrue(held)
        self.assertTrue(any('1코어 배분 불가' in r['reason'] for r in held),held)
        if p['actions']:self.service.apply(p)
        for r in held:
            old=[x for x in original['cores'] if x['core_id']==r['core_id']]
            now=[x for x in self.snapshot()['cores'] if x['core_id']==r['core_id']]
            self.assertEqual(old,now)

    def test_fixed_empty_and_cable_lock_and_fixed_identity(self):
        wf.AfterPlanner(self.app).set_fixed(slots=[(self.cables[1],1)],reason='예약')
        p=self.preview();self.assertNotIn((self.cables[1],1),p['new']);self.assertNotIn(1,[r['numbers'][1] for r in p['results'] if r['numbers']])
        wf.AfterPlanner(self.app).set_fixed(core_ids=['CORE-1'],reason='선번 유지')
        p=self.preview();self.assertEqual(self.entries(p)['CORE-1']['numbers'][1],29)
        self.s.set_node_locked(self.nodes[1],True)
        p=self.preview();self.assertFalse(p['actions']);self.assertFalse(p['mapping'])

    def test_off_broken_exception_skip_but_on_broken_remains_required(self):
        with self.s.action('대상 제외 시험'):
            self.s.conn.execute("UPDATE cores SET signal='off' WHERE core_id='CORE-1'")
            self.s.conn.execute("UPDATE cores SET status1='broken',signal='unknown' WHERE core_id='CORE-2'")
        p=self.preview();self.assertFalse(p['actions']);self.assertNotIn('CORE-1',self.entries(p));self.assertNotIn('CORE-2',self.entries(p))
        with self.s.action('예외와 ON 끊김'):
            self.s.conn.execute("UPDATE cores SET status1='exception' WHERE core_id='CORE-1'")
            self.s.conn.execute("UPDATE cores SET signal='on' WHERE core_id='CORE-2'")
        p=self.preview();self.assertEqual(self.entries(p)['CORE-1']['status'],'완료 처리')
        self.assertEqual(self.entries(p)['CORE-2']['status'],'배분 가능')
        self.service.apply(p);self.assertEqual(self.s.core(self.cables[1],29)['core_id'],'CORE-1')

    def test_fill_gaps_keeps_existing_new_numbers_and_nok_is_never_overruled(self):
        p=self.preview(mode='fill_gaps');self.assertFalse(p['actions'])
        route=wf.AfterRoutePlanner(self.app);r=route.summary()['rows'][0];problem=route.problem(r['key']);suggestion=route.recommend(problem)
        route.save(problem,suggestion,'nok');p=self.preview()
        self.assertEqual(self.entries(p)[r['core_id']]['status'],'보류')
        self.assertNotIn(r['core_id'],[x[1] for x in p['actions']])

    def test_stale_tampered_proposals_and_wrong_stage_do_not_write(self):
        p=self.preview();original=self.snapshot();changed=copy.deepcopy(p);changed['actions'].append(('x',)*6)
        with self.assertRaises(ValueError):self.service.apply(changed)
        self.assertEqual(self.snapshot(),original)
        self.service.save_settings({**wf.ALLOCATION_DEFAULTS,'reserve_tail':12})
        with self.assertRaisesRegex(ValueError,'변경'):self.service.apply(p)
        self.s.conn.execute("UPDATE meta SET value='before' WHERE key='active_scenario'");self.s.conn.commit()
        # LocalApp is a test adapter: use the actual mode to check the stage guard.
        with patch.object(self.app,'scenario_kind',return_value='before'):
            with self.assertRaises(ValueError):self.service.preview()

    def test_failure_rolls_back_whole_batch_and_reopen_keeps_rules(self):
        p=self.preview();original=self.snapshot();state=wf.state(self.s);history=self.s.history_rows()
        old=self.service._apply_rows
        def fail(*args):old(*args);raise ValueError('injected failure')
        with patch.object(self.service,'_apply_rows',side_effect=fail):
            with self.assertRaisesRegex(ValueError,'injected'):self.service.apply(p)
        self.assertEqual((self.snapshot(),wf.state(self.s),self.s.history_rows()),(original,state,history))
        self.service.save_settings({**wf.ALLOCATION_DEFAULTS,'ranges':'TRUNK=1-12','reserve_tail':12})
        path=self.s.path;self.s.close();self.app.store=code['Store'](path);self.s=self.app.store
        self.assertEqual(wf.AfterAllocator(self.app).saved_settings()['ranges'],'TRUNK=1-12')

    def test_missing_routes_remain_visible_even_when_no_current_id_exists(self):
        with self.s.action('전체 후도면 케이블 삭제'):
            self.s.conn.execute('DELETE FROM splices');self.s.conn.execute('DELETE FROM cores');self.s.conn.execute('DELETE FROM cables')
        p=self.preview();self.assertEqual(len(p['results']),2);self.assertTrue(all(r['status']=='보류' for r in p['results']))
        self.assertFalse(p['actions']);self.assertTrue(all(r['reason'] for r in p['results']))

    def test_signals_and_identity_conflicts_require_manual_resolution(self):
        with self.s.action('실제 신호 충돌'):self.s.conn.execute("UPDATE cores SET signal='off' WHERE cable_id=? AND core_index=29",(self.cables[1],))
        p=self.preview();self.assertEqual(self.entries(p)['CORE-1']['status'],'보류')
        self.assertIn('신호',self.entries(p)['CORE-1']['reason'])

    def test_full_direct_cable_uses_available_new_detour_without_touching_off_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            app=LocalApp(temp);s=app.store
            try:
                ids=drawing(app)
                with s.action('직결 케이블의 기존 OFF 선번'):
                    s.conn.execute("UPDATE cores SET core_id='RESERVED-'||core_index,signal='off' WHERE cable_id=?",(ids['direct'],))
                old=[dict(r) for r in s.cores(ids['direct'])];service=wf.AfterAllocator(app);p=service.preview()
                target=self.entries(p)['CORE-1'];self.assertEqual(target['status'],'배분 가능',target)
                self.assertNotIn(ids['direct'],target['route']);self.assertIn(ids['detour1'],target['route'])
                service.apply(p);self.assertEqual([dict(r) for r in s.cores(ids['direct'])],old)
                self.assertEqual(wf.completion_report(s)['rate'],100)
            finally:s.close()

    def test_rn_replacement_uses_existing_internal_port_and_missing_port_is_held(self):
        with tempfile.TemporaryDirectory() as temp:
            app=LocalApp(temp);s=app.store
            try:
                a=s.add_node('시작 함체',0,0);h=s.add_node('중간 함체',100,0);rn=s.add_node('RN 끝단',200,0,'rn')
                left=s.add_cable(a,h,'LEFT','6C','기설');old=s.add_cable(h,rn,'OLD','6C','기설')
                update(s,left,2,dict(core_id='RN-CORE',detail='RN 회선',signal='unknown'))
                s.connect(h,(left,2),(old,3));s.connect(rn,(old,3),('PORT:'+rn,1))
                s.backup_to(app.scenario_path('before'))
                with s.action('RN 앞 케이블 삭제'):
                    s.conn.execute('DELETE FROM splices WHERE cable1_id=? OR cable2_id=?',(old,old))
                    s.conn.execute('DELETE FROM cores WHERE cable_id=?',(old,));s.conn.execute('DELETE FROM cables WHERE id=?',(old,))
                fresh=s.add_cable(h,rn,'NEW','6C','신설');ports=[dict(r) for r in s.conn.execute('SELECT * FROM ports')]
                service=wf.AfterAllocator(app);p=service.preview();self.assertEqual(self.entries(p)['RN-CORE']['status'],'배분 가능',p['results'])
                service.apply(p);self.assertEqual(wf.completion_report(s)['rate'],100)
                self.assertEqual(s.core(fresh,2)['core_id'],'RN-CORE');self.assertEqual([dict(r) for r in s.conn.execute('SELECT * FROM ports')],ports)
                s.undo()
                with s.action('내부 포트 선번 누락'):s.conn.execute("UPDATE ports SET core_id='',detail='',signal='unknown' WHERE node_id=?",(rn,))
                p=service.preview();self.assertEqual(self.entries(p)['RN-CORE']['status'],'보류');self.assertIn('내부포트',self.entries(p)['RN-CORE']['reason'])
                self.assertFalse(p['actions'])
            finally:s.close()

    def test_invalid_rule_input(self):
        for value in ({'reserved':'3-1'},{'reserved':'아무거나'},{'ranges':'TRUNK'},{'ranges':'TRUNK='},{'reserve_tail':-1}):
            with self.assertRaises(ValueError):self.preview(**value)


def windows_gate():
    if sys.platform!='win32':return
    import faulthandler
    faulthandler.dump_traceback_later(120,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'TELECOM_APP_HOME':temp}),\
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'askyesno',return_value=True),\
         patch.object(code['messagebox'],'showerror') as error:
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(str(args))
        try:
            # Use the real App scenario folder and real workbench/button commands.
            app.store.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','after')");app.store.conn.commit()
            nodes,cables=converted(app);app.refresh();window=wf.AfterPlanDialog(app);app.update()
            panel=window.allocation_panel;window.tabs.select(window.pages['2 자동 선번 배분']);app.update()
            baseline=wf.plan_snapshot(app.store.conn);history=app.store.history_rows()
            panel.calculate_button.invoke();app.update();assert not error.called,error.call_args
            assert panel.proposal and panel.proposal['actions']
            assert len(panel.trees['코어별 배분 결과'].get_children())==2
            assert str(panel.apply_button.cget('state'))=='normal'
            assert wf.plan_snapshot(app.store.conn)==baseline and app.store.history_rows()==history
            for size in ('1340x820+0+0','1000x700+0+0'):
                window.geometry(size)
                for _ in range(3):app.update()
                assert panel.trees['코어별 배분 결과'].winfo_height()>=90
                for button in (panel.calculate_button,panel.apply_button):
                    assert button.winfo_ismapped()
                    assert button.winfo_rootx()+button.winfo_width()<=window.winfo_rootx()+window.winfo_width()
                    assert button.winfo_rooty()+button.winfo_height()<=window.winfo_rooty()+window.winfo_height()
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                path=Path(__file__).resolve().parents[1]/'dist'/'v90-auto-allocation.png';path.parent.mkdir(exist_ok=True)
                screenshot(window,path)
            panel.trees['코어별 배분 결과'].cycle_sort(1);app.update()
            panel.vars['reserve_tail'].set('12');app.update();assert panel.proposal is None and str(panel.apply_button.cget('state'))=='disabled'
            panel.calculate_button.invoke();app.update();assert not error.called,error.call_args
            panel.apply_button.invoke();app.update();assert not error.called,error.call_args
            assert wf.completion_report(app.store)['rate']==100
            assert app.store.core(cables[1],1)['core_id']=='CORE-1'
            assert '전체 연결 완료' in panel.summary.get(),panel.summary.get()
            app.store.undo();app.refresh();app.update();assert wf.plan_snapshot(app.store.conn)==baseline
            assert not errors and not error.called,(errors,error.call_args)
            window.destroy()
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows automatic allocation tab, real preview/apply buttons, draft invalidation, actual completion and atomic undo')


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(AllocationTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    windows_gate()
    print('PASS V90 after automatic numbering, baseline restoration, range matching, locks, exclusions, rollback and undo')
