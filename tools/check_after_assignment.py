"""After-drawing badges use active local topology and real end-to-end splices."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_after_plan import code,wf,LocalApp,update


def route(s):
    a=s.add_node('왼쪽 말단',150,300);h=s.add_node('중간 함체',450,300);b=s.add_node('오른쪽 말단',750,300)
    left=s.add_cable(a,h,'LEFT','12C','기설');right=s.add_cable(h,b,'RIGHT','12C','신설')
    update(s,left,1,dict(core_id='CORE',signal='on'));update(s,right,7,dict(core_id='CORE',signal='on'))
    return a,h,b,left,right


class AfterAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store
        self.a,self.h,self.b,self.left,self.right=route(self.s)
    def tearDown(self):self.s.close();self.temp.cleanup()
    def connect(self):self.s.connect(self.h,(self.left,1),(self.right,7))
    def badge(self,cable):return self.s.cable_core_warning_summary()[cable]['unassigned']

    def test_complete_terminals_with_retired_parallel_cable_have_no_false_local_badge(self):
        s=self.s;self.connect();s.add_cable(self.a,self.h,'OLD','12C','철거')
        before=wf.plan_snapshot(s.conn);history=s.history_rows()
        self.assertTrue(wf.completion_report(s)['by_id']['CORE']['complete'])
        self.assertEqual(self.badge(self.left),0);self.assertEqual(self.badge(self.right),0)
        self.assertEqual(s.node_assignment_needs(self.a),{});self.assertNotIn(self.a,s.node_warning_summary())
        self.assertEqual((wf.plan_snapshot(s.conn),s.history_rows()),(before,history))

    def test_retired_splice_cannot_make_an_assigned_live_section_unassigned(self):
        s=self.s;self.connect();old=s.add_cable(self.a,self.h,'OLD','12C','철거')
        update(s,old,1,dict(core_id='CORE',signal='on'))
        # Retained old drawing data may have both the retired and current pair.
        with s.action('보존된 철거 접속'):
            s.conn.execute('INSERT INTO splices(node_id,cable1_id,core1_index,cable2_id,core2_index) VALUES(?,?,?,?,?)',(self.h,old,1,self.right,7))
        d=s.add_node('다른 말단',150,650);e=s.add_node('배정 대기',450,650);f=s.add_node('다른 끝',750,650)
        pending=s.add_cable(d,e,'PENDING','12C','기설');s.add_cable(e,f,'EMPTY','12C','기설')
        update(s,pending,2,dict(core_id='CORE',signal='on'))
        self.assertFalse(wf.completion_report(s)['by_id']['CORE']['complete'])
        self.assertEqual(self.badge(self.left),0);self.assertEqual(self.badge(self.right),0)
        self.assertEqual(self.badge(pending),1);self.assertEqual(s.node_assignment_needs(self.h),{})
        self.assertEqual(s.node_assignment_needs(e),{pending:{2}})
        self.assertTrue(s.incomplete_core_groups()) # An unfinished island still prevents whole-ID completion.

    def test_retired_partner_is_not_a_valid_assignment_and_transit_end_is_preserved(self):
        self.connect()
        with self.s.action('오른쪽 철거'):self.s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(self.right,))
        self.assertEqual(self.badge(self.left),1);self.assertEqual(self.badge(self.right),0)
        self.assertEqual(self.s.node_assignment_needs(self.h),{self.left:{1}})
        self.assertEqual(self.s.node_warning_summary()[self.h]['count'],1)
        self.assertFalse(wf.completion_report(self.s)['by_id']['CORE']['complete'])

    def test_connection_disconnect_undo_redo_reopen_recalculates_all_badges(self):
        s=self.s;self.assertEqual((self.badge(self.left),self.badge(self.right)),(1,1))
        self.connect();self.assertFalse(s.node_assignment_needs(self.h));self.assertEqual(self.badge(self.left),0)
        s.disconnect(self.h,self.left,1);self.assertEqual(self.badge(self.left),1)
        s.undo();self.assertEqual(self.badge(self.left),0);s.redo();self.assertEqual(self.badge(self.left),1)
        s.undo();path=s.path;s.close();self.s=code['Store'](path)
        self.assertEqual(self.badge(self.left),0);self.assertFalse(self.s.node_assignment_needs(self.h))

    def test_explicit_terminal_and_rn_port_keep_distinct_completion_rules(self):
        s=self.s;self.connect();tail=s.add_node('곁가지',1050,300);s.add_cable(self.b,tail,'BRANCH','12C','기설')
        self.assertEqual(self.badge(self.right),1);s.set_node_terminal(self.b,True)
        self.assertEqual(self.badge(self.right),0);self.assertTrue(wf.completion_report(s)['by_id']['CORE']['complete'])
        rn=s.add_node('RN',1200,600,node_type='rn');end=s.add_node('RN 말단',900,600)
        cable=s.add_cable(end,rn,'RN-CABLE','12C','기설');update(s,cable,3,dict(core_id='RN-CORE',signal='on'))
        s.ensure_ports(rn,{'mp':1,'sp':1,'p':1})
        self.assertEqual(self.badge(cable),1);self.assertTrue(s.node_warning_summary()[rn]['rn_in'])
        s.connect(rn,(cable,3),('PORT:'+rn,1))
        self.assertEqual(self.badge(cable),0);self.assertNotIn(rn,s.node_warning_summary())

    def test_different_id_connection_and_unconnected_same_ids_are_not_hidden(self):
        s=self.s
        self.assertEqual(len(s.waiting_connection_groups(self.h)),1)
        self.connect()
        with s.action('접속 ID 충돌'):s.conn.execute("UPDATE cores SET core_id='DIFFERENT' WHERE cable_id=? AND core_index=7",(self.right,))
        self.assertEqual((self.badge(self.left),self.badge(self.right)),(1,1))
        self.assertEqual(s.node_assignment_needs(self.h),{self.left:{1},self.right:{7}})
        self.assertFalse(s.waiting_connection_groups(self.h))


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(a)), \
             patch.object(code['messagebox'],'showwarning',side_effect=lambda *a,**k:errors.append(a)), \
             patch.object(code['messagebox'],'showinfo',return_value=None), \
             patch.object(code['messagebox'],'askyesno',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *a:errors.append(a)
            try:
                s=app.store;s.conn.execute("INSERT INTO meta VALUES('active_scenario','after') ON CONFLICT(key) DO UPDATE SET value='after'");s.conn.commit()
                a,h,b,left,right=route(s);s.add_cable(a,h,'OLD','12C','철거');app.refresh();app.update()
                def texts():return '\n'.join(app.canvas.itemcget(x,'text') for x in app.canvas.find_all() if app.canvas.type(x)=='text')
                assert '미배정코어' in texts()
                s.connect(h,(left,1),(right,7));app.refresh();app.update()
                assert '미배정코어' not in texts() and '배정필요' not in texts(),texts()
                assert wf.core_completion_brief(s,(left,1))==('연결완료','')
                s.disconnect(h,left,1);app.refresh();app.update();assert '미배정코어' in texts()
                app.undo();app.update();assert '미배정코어' not in texts()
                assert not errors,errors
            finally:app.on_close()
    print('PASS Windows after terminal-to-terminal map badges, connected status, disconnect and undo repaint')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AfterAssignmentTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
