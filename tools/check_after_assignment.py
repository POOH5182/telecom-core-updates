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

    def test_work_marker_keeps_saved_connection_and_real_disconnect_preserves_transit_end(self):
        self.connect()
        with self.s.action('오른쪽 철거'):self.s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(self.right,))
        self.assertTrue(wf.completion_report(self.s)['by_id']['CORE']['complete'])
        self.assertEqual((self.badge(self.left),self.badge(self.right)),(0,0))
        self.assertEqual(self.s.node_assignment_needs(self.h),{})
        self.s.disconnect(self.h,self.left,1)
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

    def test_long_renumbered_route_cut_cable_removed_terminal_and_unknown_signal(self):
        s=self.s
        nodes=[self.h]+[s.add_node('신설 함체 '+str(n),450+n*180,300) for n in range(1,4)]+[self.b]
        with s.action('합성 경로 재구성'):
            s.conn.execute('DELETE FROM cores WHERE cable_id=?',(self.right,))
            s.conn.execute('DELETE FROM cables WHERE id=?',(self.right,))
            s.conn.execute("UPDATE cores SET core_id='',signal='unknown' WHERE cable_id=? AND core_index=1",(self.left,))
            s.conn.execute("UPDATE cores SET core_id='CORE',signal='on',detail='시험 회선' WHERE cable_id=? AND core_index=2",(self.left,))
        slots=[(self.left,2)]
        for index,(a,b) in enumerate(zip(nodes,nodes[1:])):
            cable=s.add_cable(a,b,'SYNTH-'+str(index),'72C' if index==3 else '144C','기설' if index==3 else '신설')
            update(s,cable,63,dict(core_id='CORE',detail='시험 회선',signal='unknown'))
            s.connect(a,slots[-1],(cable,63));slots.append((cable,63))
        with s.action('작업 표시와 번호별 신호'):
            s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(slots[-1][0],))
            s.conn.execute("UPDATE nodes SET status='철거' WHERE id=?",(self.b,))
            for cable,number in slots[1:]:s.conn.execute("UPDATE cores SET signal='unknown' WHERE cable_id=? AND core_index=?",(cable,number))
        snapshot=wf.plan_snapshot(s.conn);history=s.history_rows()
        report=wf.completion_report(s)
        self.assertEqual((report['done'],report['total'],report['rate']),(1,1,100.0))
        self.assertEqual(set(report['by_id']['CORE']['active_slots']),set(slots))
        for slot in slots:self.assertEqual(wf.core_completion_brief(s,slot),('연결완료',''))
        self.assertIn('실제 접속 완료',wf.core_completion_locations(s,slots[0]))
        self.assertFalse(s.incomplete_core_groups());self.assertFalse(report['assignment_needs'])
        self.assertEqual((wf.plan_snapshot(s.conn),s.history_rows()),(snapshot,history))
        s.disconnect(nodes[-2],*slots[-1]);self.assertEqual(wf.completion_report(s)['done'],0)
        s.undo();self.assertEqual(wf.completion_report(s)['done'],1)
        s.redo();self.assertEqual(wf.completion_report(s)['done'],0);s.undo()
        path=s.path;s.close();self.s=code['Store'](path)
        self.assertEqual(wf.completion_report(self.s)['rate'],100.0)

    def test_entire_work_marked_path_and_neutral_rn_port_count_once(self):
        s=self.s;self.connect()
        with s.action('RN 변환'):s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.a,))
        s.ensure_ports(self.a,{'mp':1,'sp':0,'p':1});port=('PORT:'+self.a,1)
        s.connect(self.a,(self.left,1),port)
        with s.action('전체 작업 표시'):
            s.conn.execute("UPDATE cables SET status='절단'")
            s.conn.execute("UPDATE nodes SET status='철거' WHERE id IN (?,?)",(self.a,self.b))
        for identity in ('','임시-시험'):
            with s.action('중립 ON 포트'):s.conn.execute("UPDATE ports SET core_id=?,signal='on' WHERE node_id=? AND port_index=1",(identity,self.a))
            report=wf.completion_report(s)
            self.assertEqual((report['done'],report['total']),(1,1),report['rows'])
            self.assertIs(report['by_slot'][port],report['by_id']['CORE'])
        s.disconnect(self.a,*port);self.assertFalse(wf.completion_report(s)['by_id']['CORE']['complete'])

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

    def test_after_rn_neutral_port_follows_actual_splice_without_writing_identity(self):
        s=self.s;self.connect()
        with s.action('RN 변환'):s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.a,))
        s.ensure_ports(self.a,{'mp':1,'sp':0,'p':1});port=('PORT:'+self.a,1)
        s.connect(self.a,(self.left,1),port)
        for identity in ('','임시-RN'):
            with self.subTest(identity=identity),s.action('중립 RN 포트'):
                s.conn.execute("UPDATE ports SET core_id=?,detail='',signal='unknown' WHERE node_id=? AND port_index=1",(identity,self.a))
            snapshot=wf.plan_snapshot(s.conn);history=s.history_rows()
            report=wf.completion_report(s)
            self.assertTrue(report['by_id']['CORE']['complete'],report['by_id']['CORE'])
            self.assertIs(report['by_slot'][port],report['by_id']['CORE'])
            self.assertEqual(wf.core_completion_brief(s,(self.left,1)),('연결완료',''))
            self.assertFalse(s.node_assignment_needs(self.a));self.assertFalse(s.incomplete_core_groups())
            self.assertEqual(s.cable_core_warning_summary()[self.left]['error'],0)
            self.assertEqual((wf.plan_snapshot(s.conn),s.history_rows()),(snapshot,history))
        s.disconnect(self.a,*port)
        self.assertFalse(wf.completion_report(s)['by_id']['CORE']['complete'])
        self.assertIn('RN 내부포트',wf.core_completion_brief(s,(self.left,1))[1])
        s.undo();self.assertTrue(wf.completion_report(s)['by_id']['CORE']['complete'])
        path=s.path;s.close();self.s=code['Store'](path)
        self.assertTrue(wf.completion_report(self.s)['by_id']['CORE']['complete'])

    def test_after_rn_work_marker_is_separate_from_conflicts_and_duplicate_splices(self):
        s=self.s;self.connect()
        with s.action('RN 변환'):s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.a,))
        s.ensure_ports(self.a,{'mp':1,'sp':0,'p':1});port=('PORT:'+self.a,1)
        s.connect(self.a,(self.left,1),port)
        for identity,signal,status in [('OTHER','unknown','normal'),('','off','normal'),('','unknown','error')]:
            with self.subTest(identity=identity,signal=signal,status=status):
                with s.action('포트 오류'):s.conn.execute("UPDATE ports SET core_id=?,signal=?,status1=? WHERE node_id=? AND port_index=1",(identity,signal,status,self.a))
                self.assertFalse(wf.completion_report(s)['by_id']['CORE']['complete'])
                s.undo()
        with s.action('빈 포트'):s.conn.execute("UPDATE ports SET core_id='' WHERE node_id=? AND port_index=1",(self.a,))
        with s.action('철거'):s.conn.execute("UPDATE cables SET status='철거' WHERE id=?",(self.left,))
        report=wf.completion_report(s)
        self.assertTrue(report['by_id']['CORE']['complete']);self.assertEqual(report['total'],1)
        self.assertIs(report['by_slot'][port],report['by_id']['CORE']);s.undo()
        with s.action('잘못된 중복 접속'):
            s.conn.execute('INSERT INTO splices(node_id,cable1_id,core1_index,cable2_id,core2_index) VALUES(?,?,?,?,?)',(self.a,port[0],port[1],self.left,1))
        self.assertFalse(wf.completion_report(s)['by_id']['CORE']['complete']);s.undo()
        update(s,*('PORT:'+self.a,2),dict(core_id='CORE',signal='on'))
        self.assertFalse(wf.completion_report(s)['by_id']['CORE']['complete'])


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
                with s.action('RN 변환'):s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(a,))
                s.ensure_ports(a,{'mp':1,'sp':0,'p':1});s.connect(a,(left,1),('PORT:'+a,1))
                with s.action('중립 RN 포트'):s.conn.execute("UPDATE ports SET core_id='',signal='unknown' WHERE node_id=? AND port_index=1",(a,))
                app.refresh();app.update();assert '미배정코어' not in texts() and '미완료코어' not in texts(),texts()
                dialog=code['CableDialog'](app,s,left);dialog.tree.selection_set('1');app.update()
                assert dialog.completion_reason.get()=='연결완료',dialog.completion_reason.get()
                with s.action('완료 경로 작업 표시'):
                    s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(right,))
                    s.conn.execute("UPDATE nodes SET status='철거' WHERE id=?",(b,))
                app.refresh();app.update()
                assert wf.completion_report(s)['rate']==100 and dialog.completion_reason.get()=='연결완료'
                assert '미완료코어' not in texts() and '미배정코어' not in texts(),texts()
                with patch.object(code['messagebox'],'showinfo') as detail:
                    dialog.completion_details_button.invoke();app.update()
                    assert detail.called and '실제 접속 완료' in detail.call_args.args[1]
                dialog.destroy()
                assert not errors,errors
            finally:app.on_close()
    print('PASS Windows after terminal-to-terminal map badges, connected status, disconnect and undo repaint')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AfterAssignmentTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
