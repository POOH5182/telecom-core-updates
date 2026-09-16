"""One core, explicit cable numbers, real map/grid clicks, atomic apply and undo."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_after_plan import code,wf,LocalApp,update
from check_after_routes import drawing


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store
        self.ids=drawing(self.app);self.source=(self.ids['left'],1);self.service=wf.ManualCoreAllocator(self.app,self.source)
    def tearDown(self):self.s.close();self.temp.cleanup()
    def snapshot(self):return wf.plan_snapshot(self.s.conn)
    def choose(self,n=7):return {**self.service.existing,self.ids['direct']:n}

    def test_selected_number_connects_all_islands_preserves_everything_and_undo(self):
        original=self.snapshot();state=wf.state(self.s);history=self.s.history_rows();before=self.app.scenario_path('before').read_bytes()
        p=self.service.preview(self.choose(7));self.assertEqual(p['selected'][self.ids['direct']],7)
        self.assertEqual(len(p['added']),2);self.assertEqual(len(p['removed']),2)
        self.assertEqual((self.snapshot(),wf.state(self.s),self.s.history_rows()),(original,state,history))
        backup=self.service.apply(p);self.assertTrue(backup.exists());self.assertEqual(self.s.core(self.ids['direct'],7)['core_id'],'CORE-1')
        self.assertEqual(self.s.core(self.ids['direct'],1)['core_id'],'')
        self.assertTrue(wf.completion_report(self.s,'after')['by_id']['CORE-1']['complete'])
        self.assertTrue(wf.AfterRoutePlanner(self.app).problem(self.service.key)['saved_ok'])
        self.assertEqual(self.app.scenario_path('before').read_bytes(),before)
        after=self.snapshot();self.s.undo();self.assertEqual(self.snapshot(),original);self.assertEqual(wf.state(self.s),state)
        self.s.redo();self.assertEqual(self.snapshot(),after)

    def test_other_ids_temporary_off_details_reservations_and_occupied_slots_are_protected(self):
        for n,fields in ((2,dict(core_id='OTHER')),(3,dict(core_id='임시-100')),(4,dict(signal='off')),(5,dict(detail='예약 내역'))):
            update(self.s,self.ids['direct'],n,fields)
        wf.AfterPlanner(self.app).set_fixed(slots=[(self.ids['direct'],6)],reason='예약')
        self.service.load();original=self.snapshot()
        for n in range(2,7):
            with self.subTest(number=n):
                self.assertFalse(self.service.availability(self.ids['direct'],n)[0])
                with self.assertRaises(ValueError):self.service.preview(self.choose(n))
        self.assertEqual(self.snapshot(),original)

    def test_existing_numbers_cannot_be_dropped_or_moved_and_branch_is_rejected(self):
        for chosen in ({self.ids['direct']:7},{**self.choose(),self.ids['left']:2},
                       {**self.choose(),self.ids['detour1']:8}):
            with self.subTest(chosen=chosen):
                with self.assertRaises(ValueError):self.service.preview(chosen)
        with self.assertRaisesRegex(ValueError,'이어지지'):self.service.preview(self.service.existing)

    def test_alternate_manual_route_and_exact_numbers(self):
        chosen={**self.service.existing,self.ids['detour1']:8,self.ids['detour2']:11}
        p=self.service.preview(chosen);self.service.apply(p)
        self.assertEqual(self.s.core(self.ids['detour1'],8)['core_id'],'CORE-1')
        self.assertEqual(self.s.core(self.ids['detour2'],11)['core_id'],'CORE-1')
        self.assertEqual(self.s.core(self.ids['direct'],1)['core_id'],'')

    def test_lock_at_new_splice_blocks_but_unchanged_locked_source_end_is_preserved(self):
        self.s.set_node_locked(self.ids['a'],True);self.service.load();p=self.service.preview(self.choose())
        self.service.apply(p);self.s.undo();self.s.set_node_locked(self.ids['b'],True);self.service.load()
        self.assertFalse(self.service.availability(self.ids['direct'],7)[0])
        with self.assertRaisesRegex(ValueError,'잠금'):self.service.preview(self.choose())

    def test_stale_tampered_wrong_stage_and_foreign_source_are_rejected(self):
        p=self.service.preview(self.choose());original=self.snapshot()
        bad=copy.deepcopy(p);bad['selected'][self.ids['direct']]=8
        with self.assertRaises(ValueError):self.service.apply(bad)
        self.assertEqual(self.snapshot(),original)
        update(self.s,self.ids['direct'],7,dict(core_id='NEW-OCCUPANT'))
        with self.assertRaisesRegex(ValueError,'변경'):self.service.apply(p)
        with patch.object(self.app,'scenario_kind',return_value='before'):
            with self.assertRaises(ValueError):wf.ManualCoreAllocator(self.app,self.source)
        with self.assertRaises(ValueError):wf.ManualCoreAllocator(self.app,(self.ids['direct'],12))

    def test_failure_rolls_back_metadata_splices_history_and_route_decision(self):
        p=self.service.preview(self.choose());original=self.snapshot();state=wf.state(self.s);history=self.s.history_rows()
        apply_rows=self.service._apply_rows
        def fail(*args):apply_rows(*args);raise ValueError('injected failure')
        with patch.object(self.service,'_apply_rows',side_effect=fail):
            with self.assertRaisesRegex(ValueError,'injected'):self.service.apply(p)
        self.assertEqual((self.snapshot(),wf.state(self.s),self.s.history_rows()),(original,state,history))

    def test_signal_conflict_never_overwrites_other_component(self):
        with self.s.action('서로 다른 신호'):
            self.s.conn.execute("UPDATE cores SET signal='off' WHERE cable_id=? AND core_index=1",(self.ids['right'],))
        self.service.load();original=self.snapshot()
        with self.assertRaisesRegex(ValueError,'신호'):self.service.preview(self.choose())
        self.assertEqual(self.snapshot(),original)

    def test_reopen_retains_assignment_and_existing_auto_rules(self):
        auto=wf.AfterAllocator(self.app);auto.save_settings({**wf.ALLOCATION_DEFAULTS,'reserved':'10-12'});rules=auto.saved_settings()
        self.service.load();self.service.apply(self.service.preview(self.choose()))
        self.s.close();self.app.store=code['Store'](self.s.path);self.s=self.app.store
        self.assertEqual(wf.AfterAllocator(self.app).saved_settings(),rules)
        self.assertEqual(self.s.core(self.ids['direct'],7)['core_id'],'CORE-1')
        self.assertTrue(wf.AfterRoutePlanner(self.app).problem(self.service.key)['saved_ok'])

    def test_join_at_same_enclosure_needs_only_splice_no_new_assignment(self):
        with tempfile.TemporaryDirectory() as d:
            app=LocalApp(d);s=app.store
            try:
                a=s.add_node('A',0,0);b=s.add_node('B',200,0);c=s.add_node('C',400,0)
                left=s.add_cable(a,b,'L','12C','기설');right=s.add_cable(b,c,'R','12C','기설')
                update(s,left,2,dict(core_id='JOIN',signal='on'));update(s,right,9,dict(core_id='JOIN',signal='on'))
                s.backup_to(app.scenario_path('before'));service=wf.ManualCoreAllocator(app,(left,2));p=service.preview(service.existing)
                self.assertFalse(p['new']);self.assertEqual(len(p['added']),1);service.apply(p)
                self.assertTrue(wf.completion_report(s,'after')['by_id']['JOIN']['complete'])
            finally:s.close()


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[];warnings=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(a)), \
             patch.object(code['messagebox'],'showwarning',side_effect=lambda *a,**k:warnings.append(a)), \
             patch.object(code['messagebox'],'showinfo',return_value=None), \
             patch.object(code['messagebox'],'askyesno',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *a:errors.append(a)
            try:
                # Same actual after-stage entry used by the automatic allocator.
                app.store.conn.execute("INSERT INTO meta(key,value) VALUES('active_scenario','after') ON CONFLICT(key) DO UPDATE SET value='after'")
                app.store.conn.commit();i=drawing(app);app.refresh();app.update()
                editor=code['open_detail_dialog'](app,app.store,'cable',i['left']);editor.focus_core(1);app.update()
                original=wf.plan_snapshot(app.store.conn);editor.manual_allocation_button.invoke();app.update()
                dialog=app._manual_allocation_window;assert isinstance(dialog,wf.ManualCoreAllocationDialog)
                assert len(dialog.service.problem['components'])==2 and app.highlight_owner is dialog
                assert editor.winfo_exists() and not editor._core_trace_enabled
                # Real pointer event on the route map cable label.
                tag='manual_cable:'+i['direct'];items=dialog.map.find_withtag(tag);assert items
                item=next(x for x in items if dialog.map.type(x)=='text');x,y=dialog.map.coords(item)
                dialog.map.event_generate('<Button-1>',x=int(x-dialog.map.canvasx(0)),y=int(y-dialog.map.canvasy(0)));app.update()
                assert i['direct'] in dialog.columns and i['direct'] not in dialog.selected
                assert wf.plan_snapshot(app.store.conn)==original
                # Select number 7 through the scrolling grid's actual click.
                dialog.sheet.yview_moveto(0);dialog.scroll_x('moveto',0);app.update()
                col=dialog.columns.index(i['direct']);x=dialog.GUTTER+(col+.5)*dialog.CELL_W;y=6.5*dialog.CELL_H
                dialog.sheet.yview_moveto(max(0,(y-100)/(12*dialog.CELL_H)));app.update()
                dialog.sheet.event_generate('<Button-1>',x=int(x-dialog.sheet.canvasx(0)),y=int(y-dialog.sheet.canvasy(0)));app.update()
                assert dialog.selected[i['direct']]==7 and wf.plan_snapshot(app.store.conn)==original
                assert len(dialog.map.find_withtag('manual_cable:'+i['right']))>=2
                # Inspecting an assigned existing number keeps the chosen draft.
                dialog.choose_slot(i['left'],1);app.update()
                assert dialog.inspected==(i['left'],1) and dialog.inspect_cables
                assert dialog.selected[i['direct']]==7 and wf.plan_snapshot(app.store.conn)==original
                # Preview cancellation preserves the draft and physical state.
                def review_action(accept):
                    review=next(w for w in dialog.winfo_children() if isinstance(w,wf.ManualAllocationReview))
                    (review.confirm if accept else review.destroy)()
                dialog.after(120,lambda:review_action(False));dialog.apply_button.invoke();app.update()
                assert wf.plan_snapshot(app.store.conn)==original and dialog.selected[i['direct']]==7
                dialog.after(120,lambda:review_action(True));dialog.apply_button.invoke();app.update()
                assert app.store.core(i['direct'],7)['core_id']=='CORE-1'
                assert wf.completion_report(app.store,'after')['by_id']['CORE-1']['complete']
                dialog.sheet.focus_force();app.update();dialog.sheet.event_generate('<Control-z>');app.update()
                assert dialog.stale and str(dialog.apply_button['state'])=='disabled'
                assert wf.plan_snapshot(app.store.conn)==original
                dialog.run(dialog.reload);app.update();assert not dialog.stale
                dialog.geometry('1000x700');app.update();dialog.apply_button.master.reflow();app.update()
                assert dialog.apply_button.winfo_viewable() and dialog.sheet.winfo_height()>70
                assert dialog.apply_button.winfo_rootx()+dialog.apply_button.winfo_width()<=dialog.winfo_rootx()+dialog.winfo_width()
                dialog.destroy();app.update();assert editor._core_trace_enabled and app.highlight_owner is not dialog
                assert not errors,errors;assert not warnings,warnings
            finally:app.on_close()
    print('PASS Windows cable core button, real map/grid clicks, draft cancel, reviewed apply, undo/stale, narrow view and highlight cleanup')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ManualTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS manual one-core allocation, exact numbers, conflict/lock preservation, preview, backups, rollback and undo')
