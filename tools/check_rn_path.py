"""RN editor physical path selection and after-only IN assignment badge policy."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from check_field_survey import code,wf


def fixture(path,kind='before'):
    s=code['Store'](path);s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario',?)",(kind,))
    s.conn.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('field_identity_policy',wf.FIELD_SLOT_POLICY));s.conn.commit()
    rn=s.add_node('예시 RN',120,200,node_type='rn');h=s.add_node('예시 함체',420,200);a=s.add_node('끝단 A',720,200)
    left=s.add_cable(rn,h,'SYNTH-LEFT','6C','기설');right=s.add_cable(h,a,'SYNTH-RIGHT','6C','기설')
    s.update_core(left,1,('SYNTH-1','RN 경로','normal','','unknown'))
    s.connect(rn,('PORT:'+rn,1),(left,1));s.connect(h,(left,1),(right,3))
    wf.rn_identity_save(s,rn,[(1,'SYNTH-1','RN 경로'),(2,'UNCONNECTED','미접속 포트')],s.data_revision(),s._view_generation)
    return s,rn,h,left,right


class RNPathTests(unittest.TestCase):
    def test_path_neutral_transit_id_conflict_and_same_id_context_readonly(self):
        with tempfile.TemporaryDirectory() as temp:
            s,rn,h,left,right=fixture(Path(temp)/'drawing.sqlite3')
            try:
                before=wf.plan_snapshot(s.conn);history=s.history_rows()
                path=wf.rn_identity_path(s,rn,1);self.assertEqual(set(path['model']['colors']),{left,right})
                self.assertIn('실제 연결 2개',path['summary']);self.assertEqual(path['slot'],('PORT:'+rn,1))
                self.assertFalse(wf.rn_identity_path(s,rn,2)['model']['colors']);self.assertFalse(wf.rn_identity_path(s,rn,3)['model']['colors'])
                self.assertEqual(wf.plan_snapshot(s.conn),before);self.assertEqual(s.history_rows(),history)
                s.update_core(right,3,('OTHER','충돌 내역','normal','','unknown'))
                self.assertEqual(set(wf.rn_identity_path(s,rn,1)['model']['colors']),{left,right})
                s.update_core(right,5,('SYNTH-1','분리된 같은 ID','normal','','unknown'))
                model=wf.rn_identity_path(s,rn,1)['model'];self.assertEqual(len(model['groups']),2)
                self.assertEqual(sum(g['selected'] for g in model['groups']),1)
                s.disconnect(h,left,1);self.assertIn('실제 연결 1개',wf.rn_identity_path(s,rn,1)['summary'])
            finally:s.close()

    def test_after_in_badge_only_preserves_other_needs_history_and_field_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            s,rn,h,left,right=fixture(Path(temp)/'drawing.sqlite3','after')
            try:
                self.assertTrue(s.node_assignment_needs(rn)) # MP1 is still physically unconnected.
                before=wf.plan_snapshot(s.conn);history=s.history_rows()
                self.assertTrue(wf.after_rn_in_connected(s,rn));badge=s.node_warning_summary().get(rn,{})
                self.assertFalse(badge.get('rn_in'));self.assertFalse(badge.get('count'))
                self.assertEqual(wf.plan_snapshot(s.conn),before);self.assertEqual(s.history_rows(),history)
                self.assertFalse(wf.completion_report(s)['by_id']['UNCONNECTED']['complete'])
                s.disconnect(rn,left,1);self.assertFalse(wf.after_rn_in_connected(s,rn));self.assertTrue(s.node_warning_summary()[rn]['rn_in'])
                s.undo();self.assertFalse(s.node_warning_summary().get(rn,{}).get('rn_in'));s.redo();self.assertTrue(s.node_warning_summary()[rn]['rn_in'])
                s.undo();path=s.path;s.close();s=code['Store'](path);self.assertFalse(s.node_warning_summary().get(rn,{}).get('rn_in'))
                for stage in ('gis','before'):
                    with s.action('합성 단계 변경'):s.conn.execute("UPDATE meta SET value=? WHERE key='active_scenario'",(stage,))
                    self.assertFalse(wf.after_rn_in_connected(s,rn));self.assertTrue(s.node_warning_summary()[rn]['rn_in'])
            finally:s.close()

    def test_rn_sp5_to_cable5_to_rn_in_complete_in_all_stages(self):
        with tempfile.TemporaryDirectory() as temp:
            s=code['Store'](Path(temp)/'rn_to_rn.sqlite3')
            try:
                a=s.add_node('같은 이름 RN',0,0,node_type='rn');b=s.add_node('같은 이름 RN',300,0,node_type='rn')
                s.ensure_ports(a,{'mp':4,'sp':5,'p':4});sp5=next(r['core_index'] for r in s.cores('PORT:'+a) if r['label']=='SP5')
                c=s.add_cable(a,b,'SYNTH-RN','12C','기설');s.update_core(c,5,('RN-TO-RN','RN 내부 간 회선','normal','','on'))
                s.connect(a,('PORT:'+a,sp5),(c,5));s.connect(b,(c,5),('PORT:'+b,1))
                before=wf.plan_snapshot(s.conn)
                for stage in ('gis','before','after'):
                    s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario',?)",(stage,));s.conn.commit();s._cable_warning_cache=None;s._warning_cache=None
                    self.assertTrue(wf.Network(s.conn).inspect('RN-TO-RN',wf.DEFAULTS)['complete'])
                    self.assertTrue(wf.completion_report(s)['by_id']['RN-TO-RN']['complete'])
                    badge=s.cable_core_warning_summary()[c];self.assertEqual(badge['incomplete'],0);self.assertEqual(badge['unassigned'],0)
                    self.assertFalse(s.node_assignment_needs(a));self.assertFalse(s.node_assignment_needs(b))
                    self.assertFalse(s.trace_core_paths('RN-TO-RN',slot=(c,5))['issues'])
                self.assertEqual(wf.plan_snapshot(s.conn)['splices'],before['splices'])
                self.assertFalse(wf.valid_endpoint_pair([('rn',a,'SP5'),('rn',a,'IN')]))
                s.disconnect(b,c,5);self.assertFalse(wf.completion_report(s)['by_id']['RN-TO-RN']['complete'])
                s.undo();self.assertTrue(wf.completion_report(s)['by_id']['RN-TO-RN']['complete'])
                wf.rn_identity_save(s,b,[(1,'CONFLICT','')],s.data_revision(),s._view_generation)
                self.assertFalse(wf.completion_report(s)['by_id']['RN-TO-RN']['complete'])
            finally:s.close()

    def test_wrong_port_or_duplicate_in_splice_does_not_hide_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            s,rn,h,left,right=fixture(Path(temp)/'drawing.sqlite3','after')
            try:
                s.disconnect(rn,left,1)
                s.update_core(left,2,('UNCONNECTED','MP 접속','normal','','unknown'));s.connect(rn,('PORT:'+rn,2),(left,2))
                self.assertFalse(wf.after_rn_in_connected(s,rn));self.assertTrue(s.node_warning_summary()[rn]['rn_in'])
                with s.action('합성 중복 IN 접속'):
                    for i in (1,3):s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(rn,'PORT:'+rn,1,left,i))
                self.assertFalse(wf.after_rn_in_connected(s,rn));self.assertTrue(s.node_warning_summary()[rn]['rn_in'])
            finally:s.close()


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=str(Path(temp)/'ui')),patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showerror') as error:
        Path(temp,'ui').mkdir();s,rn,h,left,right=fixture(Path(temp)/'drawing.sqlite3');s.close()
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        def pump(seconds=.08):
            end=time.monotonic()+seconds
            while time.monotonic()<end:app.update();time.sleep(.01)
        def click_row(editor,index):
            editor.tree.see(str(index));app.update();x,y,w,hei=editor.tree.bbox(str(index))
            editor.tree.event_generate('<ButtonPress-1>',x=x+25,y=y+hei//2);editor.tree.event_generate('<ButtonRelease-1>',x=x+25,y=y+hei//2);pump()
        try:
            app.replace_current_from(Path(temp)/'drawing.sqlite3');app.deiconify();app.update();s=app.store
            node=code['NodeDialog'](app,s,rn);app.update();node.rn_identity_button.invoke();pump();editor=node._rn_identity_dialog
            before=wf.plan_snapshot(s.conn);history=s.history_rows();click_row(editor,1)
            assert app.highlight_owner is editor and app.highlight_cables=={left,right}
            assert app._highlight_seeds==(('PORT:'+rn,1),) and app.canvas.find_withtag('core_path_number')
            observed=set()
            for _ in range(10):pump(.08);observed.add(app.highlight_blink_on)
            assert observed=={True,False}
            editor.detail.set('아직 저장하지 않은 입력');click_row(editor,2)
            assert not app.highlight_cables and '아직 연결된' in editor.path_notice.get()
            click_row(editor,1);assert editor.detail.get()=='아직 저장하지 않은 입력' and app.highlight_cables=={left,right}
            assert wf.plan_snapshot(s.conn)==before and s.history_rows()==history
            s.disconnect(h,left,1);app.refresh();pump();assert app.highlight_cables=={left}
            assert editor.detail.get()=='아직 저장하지 않은 입력'
            s.undo();app.refresh();pump();assert app.highlight_cables=={left,right}
            from check_desktop_design import screenshot
            screenshot(editor,Path(temp)/'v131-rn-path.png')
            # Clear/another owner must not be reclaimed by ordinary repaint or close.
            app.clear_highlight();app.refresh();pump();assert not app.highlight_cables
            click_row(editor,1);other=object();app.start_highlight_blink({left},owner=other,core_slots=[(left,1)])
            with patch.object(code['messagebox'],'askyesno',return_value=True):editor.close()
            pump();assert app.highlight_owner is other
            node.rn_identity_button.invoke();pump();editor=node._rn_identity_dialog;click_row(editor,1)
            editor.destroy();pump();assert not app.highlight_cables and app.highlight_blink_job is None
            # Actual canvas badge follows IN only in after; diagnostics still exist.
            node.destroy()
            with s.action('합성 후도면 전환'):s.conn.execute("UPDATE meta SET value='after' WHERE key='active_scenario'")
            app.refresh();pump()
            labels=lambda:[app.canvas.itemcget(i,'text') for i in app.canvas.find_all() if app.canvas.type(i)=='text']
            assert 'RN 내부 배정필요' not in labels()
            s.disconnect(rn,left,1);app.refresh();pump();assert 'RN 내부 배정필요' in labels()
            s.undo();app.refresh();pump();assert 'RN 내부 배정필요' not in labels()
            assert not errors and not error.called,(errors,error.call_args)
            print('PASS Windows RN saved port click, real cable blinking, drafts, disconnect/undo, owner cleanup and after IN canvas badge')
        finally:app.store.close();app.destroy()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RNPathTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
