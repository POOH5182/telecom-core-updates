"""V183: 자동배정 for one core in 후도면 · 코어배정.

Numbers stay the same through every enclosure except the enclosures the user
allowed to turn (틀어도 되는 함체, saved per drawing). Not allowed turns are
reported as forced; the plan saves through the normal incremental allocator.
"""
import faulthandler
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_after_plan import code,wf,LocalApp,update
from check_after_routes import drawing
from check_manual_allocation import clear_old_connector


class CoreAutoAssign(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);s=self.s=self.app.store
        self.n=[s.add_node('함체 '+str(i),i*200,100) for i in range(5)]
        s.backup_to(self.app.scenario_path('before'))
        self.c=[s.add_cable(self.n[i],self.n[i+1],'NEW'+str(i+1),'24C','신설') for i in range(4)]
        update(s,self.c[0],5,dict(core_id='CORE-A',detail='A 회선',signal='on'))
    def tearDown(self):self.s.close();self.temp.cleanup()

    def service(self):return wf.RNIncrementalCoreAllocator(self.app,(self.c[0],5),allow_excluded=True)

    def plan(self,allowed=None):
        service=self.service()
        return service,wf.core_auto_plan(service,list(self.c),dict(service.existing),wf.turn_nodes(self.s) if allowed is None else allowed)

    def test_same_number_through_every_enclosure(self):
        service,plan=self.plan()
        self.assertEqual(plan['numbers'],{self.c[1]:5,self.c[2]:5,self.c[3]:5})
        self.assertEqual(plan['turns'],[]);self.assertEqual(plan['source'],'클릭한 케이블')
        p=service.preview({**service.existing,**plan['numbers']});service.apply(p)
        self.assertEqual(self.s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0],3)
        self.assertTrue(wf.completion_report(self.s,'after')['by_id']['CORE-A']['complete'])

    def test_turn_only_at_allowed_enclosure(self):
        update(self.s,self.c[2],5,dict(core_id='OTHER',detail='사용 중',signal='on'))
        _,plan=self.plan(set())
        self.assertEqual(len(plan['forced']),1,plan['turns'])
        wf.save_turn_nodes(self.s,{self.n[2]})
        self.assertEqual(wf.turn_nodes(self.s),{self.n[2]})
        _,plan=self.plan()
        self.assertFalse(plan['forced'],plan['turns'])
        self.assertEqual(plan['numbers'][self.c[1]],5)
        self.assertNotEqual(plan['numbers'][self.c[2]],5)
        # Not allowed at 함체 3: the new number continues straight on.
        self.assertEqual(plan['numbers'][self.c[3]],plan['numbers'][self.c[2]])
        self.assertEqual([t['node'] for t in plan['turns']],[self.n[2]])

    def test_turn_back_when_allowed_later(self):
        update(self.s,self.c[2],5,dict(core_id='OTHER',detail='사용 중',signal='on'))
        update(self.s,self.c[3],6,dict(core_id='OTHER2',detail='사용 중',signal='on'))
        _,plan=self.plan({self.n[1]})
        # Turning once at 함체 1 is enough; the number then stays the same.
        self.assertFalse(plan['forced'])
        values=[plan['numbers'][c] for c in self.c[1:]]
        self.assertEqual(len(set(values)),1,values);self.assertNotIn(values[0],(5,6))

    def test_user_draft_number_is_kept(self):
        service=self.service()
        plan=wf.core_auto_plan(service,list(self.c),{**service.existing,self.c[2]:9},set())
        self.assertEqual(plan['numbers'][self.c[2]],9)
        self.assertEqual(plan['numbers'][self.c[3]],9)

    def test_branch_is_refused(self):
        extra=self.s.add_node('가지 함체',400,300)
        branch=self.s.add_cable(self.n[2],extra,'BR','24C','신설')
        service=self.service()
        with self.assertRaises(ValueError):wf.core_auto_plan(service,list(self.c)+[branch],dict(service.existing),set())

    def test_no_free_number(self):
        for i in range(1,25):update(self.s,self.c[1],i,dict(core_id='X'+str(i),detail='사용',signal='on'))
        service=self.service()
        with self.assertRaises(ValueError) as error:wf.core_auto_plan(service,list(self.c),dict(service.existing),set())
        self.assertIn('빈 번호',str(error.exception))

    def test_panel_has_buttons(self):
        self.assertTrue(issubclass(wf.MapCoreAllocationPanel,wf.CoreAutoAssignActions))
        for name in ('auto_assign','choose_turn_nodes'):self.assertTrue(callable(getattr(wf.MapCoreAllocationPanel,name)))

    def test_recommended_route_without_clicks(self):
        with tempfile.TemporaryDirectory() as temp:
            local=LocalApp(temp);i=drawing(local)
            update(local.store,i['direct'],1,dict(core_id='OTHER',detail='사용 중',signal='on'))
            service=wf.RNIncrementalCoreAllocator(local,(i['left'],1))
            plan=wf.core_auto_plan(service,[],dict(service.existing),set())
            self.assertEqual(plan['source'],'추천 경로')
            self.assertEqual(set(plan['numbers']),{i['direct']})
            self.assertEqual(len(plan['forced']),2,plan['turns'])
            plan=wf.core_auto_plan(service,[],dict(service.existing),{i['b'],i['c']})
            self.assertFalse(plan['forced']);self.assertEqual(plan['numbers'][i['direct']],2)
            local.store.close()


def windows_ui():
    if sys.platform!='win32':
        print('Core auto-assign button gate runs on Windows.');return
    faulthandler.dump_traceback_later(100,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showerror') as error,patch.object(code['messagebox'],'showwarning') as warning, \
         patch.object(code['messagebox'],'showinfo'):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            app.geometry('1450x950+0+0');s=app.store
            s.conn.execute("INSERT INTO meta VALUES('active_scenario','after') ON CONFLICT(key) DO UPDATE SET value='after'");s.conn.commit()
            i=drawing(app);clear_old_connector(app,i)
            update(s,i['direct'],1,dict(core_id='OTHER',detail='사용 중',signal='on'))
            app.refresh();app.update();app.fit_view();app.update()
            editor=code['open_detail_dialog'](app,s,'cable',i['left']);editor.focus_core(1);app.update()
            editor.map_allocation_button.invoke();app.update();panel=app._map_allocation_panel
            assert isinstance(panel,wf.MapCoreAllocationPanel)
            assert panel.auto_button.winfo_exists() and panel.turn_button.winfo_exists()
            original=wf.plan_snapshot(s.conn)
            # Not allowed to turn anywhere: asks first; 아니오 makes no draft.
            with patch.object(code['messagebox'],'askyesno',return_value=False) as ask:
                panel.auto_button.invoke();app.update()
            assert ask.called and i['direct'] not in panel.selected and wf.plan_snapshot(s.conn)==original
            # Choose 틀어도 되는 함체 in the dialog.
            def pick():
                dialog=next(w for w in panel.winfo_children() if isinstance(w,wf.TurnNodesDialog))
                for k,node in enumerate(dialog.nodes):
                    if node in (i['b'],i['c']):dialog.list.selection_set(k)
                dialog.confirm()
            app.after(150,pick);panel.turn_button.invoke();app.update()
            assert wf.turn_nodes(s)=={i['b'],i['c']},wf.turn_nodes(s)
            assert '틀어도 되는 함체' in panel.message.get()
            def answer():
                review=next(w for w in app.winfo_children() if isinstance(w,wf.ManualAllocationReview));review.confirm()
            with patch.object(code['messagebox'],'askyesno',side_effect=AssertionError('no forced turn expected')):
                app.after(150,answer);panel.auto_button.invoke();app.update()
            assert s.core(i['direct'],2)['core_id']=='CORE-1',dict(s.core(i['direct'],2))
            assert wf.completion_report(s,'after')['by_id']['CORE-1']['complete']
            assert '배정 저장 완료' in panel.message.get()
            panel.close_requested();app.update()
            assert not errors,errors;assert not error.called,error.call_args_list;assert not warning.called,warning.call_args_list
        finally:app.on_close();faulthandler.cancel_dump_traceback_later()
    print('PASS core auto-assign button: forced-turn question, turn enclosure dialog, one-click save')


if __name__=='__main__':
    result=unittest.main(verbosity=2,exit=False).result
    if not result.wasSuccessful():
        print('::error::check_core_auto_assign unit tests failed');raise SystemExit(1)
    try:windows_ui()
    except Exception as exc:
        import traceback;traceback.print_exc();print('::error::check_core_auto_assign UI: '+ascii(exc));raise SystemExit(1)
    print('PASS check_core_auto_assign')
