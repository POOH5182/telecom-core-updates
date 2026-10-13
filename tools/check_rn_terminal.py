"""V128 explicit RN endpoints without internal splices; legacy default stays strict."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_field_survey import code,wf


def fixture(path,kind='before',slots=True):
    s=code['Store'](path)
    s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario',?)",(kind,))
    if slots:s.conn.execute("INSERT OR REPLACE INTO meta VALUES('field_identity_policy',?)",(wf.FIELD_SLOT_POLICY,))
    s.conn.commit();a=s.add_node('합성 끝단',0,0);rn=s.add_node('합성 RN',260,0,node_type='rn')
    c=s.add_cable(a,rn,'SYNTH-RN','6C','기설')
    s.update_core(c,1,('SYNTH-1','RN 끝단 시험','normal','','unknown'))
    return s,a,rn,c


class RNTerminalTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);self.stores=[]
    def tearDown(self):
        for s in self.stores:s.close()
        self.temp.cleanup()
    def make(self,kind='before',slots=True):
        result=fixture(self.home/(kind+str(len(self.stores))+'.sqlite3'),kind,slots);self.stores.append(result[0]);return result
    def snap(self,s):return wf.plan_snapshot(s.conn),wf.state(s)
    def test_opt_in_all_stages_completion_trace_needs_history_and_reopen(self):
        for kind,slots in (('gis',False),('before',False),('before',True),('after',True)):
            with self.subTest(kind=kind,slots=slots):
                s,a,rn,c=self.make(kind,slots);before=self.snap(s)
                self.assertFalse(wf.completion_report(s)['by_id']['SYNTH-1']['complete'])
                self.assertTrue(s.node_assignment_needs(rn))
                s.set_node_terminal(rn,True)
                self.assertTrue(wf.terminal_marked(s.node(rn)))
                self.assertTrue(wf.completion_report(s)['by_id']['SYNTH-1']['complete'],wf.completion_report(s)['by_id']['SYNTH-1'])
                self.assertTrue(wf.Network(s.conn).inspect('SYNTH-1',wf.DEFAULTS)['complete'])
                self.assertFalse(s.node_assignment_needs(rn));self.assertFalse(s.waiting_connection_groups(rn))
                self.assertFalse(s.trace_core_paths('SYNTH-1')['issues'])
                self.assertFalse(s.node_warning_summary().get(rn,{}).get('rn_in'))
                self.assertFalse(wf.field_required(s,s.node(rn)))
                after=self.snap(s)
                for table in before[0]:
                    if table not in ('nodes','meta'):self.assertEqual(before[0][table],after[0][table],table)
                s.undo();self.assertEqual(self.snap(s),before);s.redo();self.assertEqual(self.snap(s),after)
                path=s.path;s.close();self.stores.remove(s);s=code['Store'](path);self.stores.append(s)
                self.assertTrue(wf.completion_report(s)['by_id']['SYNTH-1']['complete'])
                s.set_node_terminal(rn,False);self.assertFalse(wf.completion_report(s)['by_id']['SYNTH-1']['complete'])
    def test_legacy_flag_does_not_auto_enable_and_unrelated_rn_stays_incomplete(self):
        s,a,rn,c=self.make()
        with s.action('합성 구버전 플래그'):s.conn.execute("UPDATE nodes SET extra_json=json_set(extra_json,'$.terminal',1) WHERE id=?",(rn,))
        self.assertFalse(wf.terminal_marked(s.node(rn)))
        other=s.add_node('다른 RN',500,0,node_type='rn');c2=s.add_cable(a,other,'OTHER','6C','기설')
        s.set_node_terminal(a,True);s.update_core(c2,1,('SYNTH-2','다른 구간','normal','','unknown'))
        s.set_node_terminal(rn,True)
        self.assertTrue(wf.completion_report(s)['by_id']['SYNTH-1']['complete'])
        self.assertFalse(wf.completion_report(s)['by_id']['SYNTH-2']['complete'])
        s.set_node_terminal(rn,False);self.assertFalse(wf.terminal_marked(s.node(rn)))
    def test_existing_splice_and_port_remain_and_conflicts_are_not_bypassed(self):
        s,a,rn,c=self.make();port=s.cores('PORT:'+rn)[0]['core_index']
        s.connect(rn,(c,1),('PORT:'+rn,port));before=self.snap(s)
        s.set_node_terminal(rn,True)
        self.assertEqual(before[0]['splices'],self.snap(s)[0]['splices']);self.assertEqual(before[0]['ports'],self.snap(s)[0]['ports'])
        s.update_core('PORT:'+rn,port,('OTHER-ID','다른 실제 코어','normal','','off'))
        self.assertFalse(wf.completion_report(s)['by_id']['SYNTH-1']['complete'])
        self.assertTrue(s.trace_core_paths('SYNTH-1')['issues'])
    def test_after_endpoint_toggle_and_later_edits_do_not_auto_join_at_marked_rn(self):
        s,a,rn,c=self.make('after');b=s.add_node('반대 끝',500,0);other=s.add_cable(rn,b,'SECOND','6C','기설')
        s.update_core(other,1,('SYNTH-1','RN 끝단 시험','normal','','unknown'))
        s.conn.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(wf.AFTER_AUTO_POLICY,'1'));s.conn.commit()
        before=self.snap(s)[0]['splices']
        s.set_node_terminal(rn,True);self.assertEqual(self.snap(s)[0]['splices'],before)
        s.update_core(c,1,('SYNTH-1','수정한 내역','normal','','unknown'))
        self.assertEqual(self.snap(s)[0]['splices'],before)
        s.set_node_terminal(rn,False);self.assertEqual(self.snap(s)[0]['splices'],before)

    def test_multi_cable_rn_terminal_does_not_join_routes_or_change_source_snapshots(self):
        s,a,rn,c=self.make();b=s.add_node('합성 끝단 B',500,0);other=s.add_cable(rn,b,'SECOND','6C','기설')
        s.update_core(other,1,('SECOND-ID','두 번째 회선','normal','','unknown'))
        source=self.home/'gis_saved.sqlite3';s.backup_to(source);original=source.read_bytes()
        before=self.snap(s);s.set_node_terminal(rn,True)
        self.assertTrue(all(wf.completion_report(s)['by_id'][cid]['complete'] for cid in ('SYNTH-1','SECOND-ID')))
        self.assertEqual(before[0]['splices'],self.snap(s)[0]['splices']);self.assertEqual(source.read_bytes(),original)
        # Same identity on two disconnected paths must still be diagnosed.
        s.update_core(other,1,('SYNTH-1','두 번째 회선','normal','','unknown'))
        self.assertFalse(wf.completion_report(s)['by_id']['SYNTH-1']['complete'])


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=str(Path(temp)/'ui')),patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showerror') as error,patch.object(code['messagebox'],'askyesno',return_value=True):
        Path(temp,'ui').mkdir();s,a,rn,c=fixture(Path(temp)/'drawing.sqlite3');s.close()
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            app.replace_current_from(Path(temp)/'drawing.sqlite3');app.deiconify();app.update();s=app.store
            node=code['NodeDialog'](app,s,rn);app.update();before=wf.plan_snapshot(s.conn)
            check=node.terminal_check;assert check.winfo_ismapped()
            check.event_generate('<ButtonPress-1>',x=7,y=7);check.event_generate('<ButtonRelease-1>',x=7,y=7);app.update()
            assert wf.terminal_marked(s.node(rn)) and wf.completion_report(s)['by_id']['SYNTH-1']['complete']
            from check_desktop_design import screenshot
            screenshot(node,Path(temp)/'v128-rn-terminal.png')
            after=wf.plan_snapshot(s.conn);s.undo();app.refresh();app.update();assert not node.terminal_var.get()
            assert wf.plan_snapshot(s.conn)==before
            s.redo();app.refresh();app.update();assert node.terminal_var.get() and wf.plan_snapshot(s.conn)==after
            # Properties cancellation preserves the live drawing.
            prop=code['NodePropertiesDialog'](app,s,rn);app.update();assert prop.terminal.get()
            prop.terminal.set(False);prop.destroy();assert wf.plan_snapshot(s.conn)==after
            prop=code['NodePropertiesDialog'](app,s,rn);prop.terminal.set(False);app.update()
            def widgets(w):
                for ch in w.winfo_children():yield ch;yield from widgets(ch)
            button=next(w for w in widgets(prop) if isinstance(w,code['ttk'].Button) and str(w.cget('text'))=='저장')
            button.invoke();app.update();assert not wf.terminal_marked(s.node(rn))
            assert not node.terminal_var.get() and not wf.completion_report(s)['by_id']['SYNTH-1']['complete']
            node.destroy();assert not errors and not error.called,(errors,error.call_args_list)
        finally:app.on_close()
    print('PASS Windows RN terminal checkbox, completion, properties cancel/save, undo/redo and shared refresh')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RNTerminalTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
