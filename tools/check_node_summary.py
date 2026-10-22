"""V77 identity rows preserve actual splices, physical edit targets and drafts."""
import os
import sys
import unittest
from unittest.mock import patch

from check_field_slots import SlotFieldTests,code,wf


class SummaryTests(unittest.TestCase):
    setUp=SlotFieldTests.setUp
    tearDown=SlotFieldTests.tearDown
    slot=SlotFieldTests.slot
    set=SlotFieldTests.set
    apply=SlotFieldTests.apply
    snapshot=SlotFieldTests.snapshot
    splices=SlotFieldTests.splices

    def rows(self):
        return code['node_summary_rows'](self.s,self.nodes[1],[('A',self.cables[0]),('B',self.cables[1])])

    def containing(self,slot):return next(r for r in self.rows() if slot in r['slots'])

    def test_equal_id_is_one_numeric_row_without_connecting_or_completing(self):
        self.set(1,1,'','','unknown');self.set(1,2,'CORE-A','GIS 내역','on')
        before=self.snapshot();revision=self.s.data_revision();history=self.s.conn.execute('SELECT COUNT(*) FROM history_groups').fetchone()[0]
        row=self.containing(self.slot(0))
        self.assertEqual(row['values'][:5],('CORE-A','GIS 내역','1','2','배정필요'))
        self.assertEqual(set(row['slots']),{self.slot(0),self.slot(1,2)})
        self.assertEqual(len([r for r in self.rows() if r['values'][0]=='CORE-A']),1)
        self.assertNotIn('↔',row['connection']);self.assertNotIn('번',row['connection'])
        self.assertEqual(self.splices(),[]);self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.s.data_revision(),revision)
        self.assertEqual(self.s.conn.execute('SELECT COUNT(*) FROM history_groups').fetchone()[0],history)
        self.assertEqual(self.s.trace_core_paths('CORE-A',slot=self.slot(0))['highlight'],{self.cables[0]})
        self.assertEqual(wf.completion_report(self.s)['done'],0)

    def test_group_keeps_actual_pair_and_unconnected_positions_separate(self):
        self.apply(1,'A\tB\n1\t1');self.set(0,3,'CORE-A','다른 이름','off')
        before=self.snapshot();row=self.containing(self.slot(0))
        self.assertEqual(row['values'][2:5],('1 · 3','1','연결 / 집계 제외'))
        self.assertIn('다른 이름',row['values'][1]);self.assertIn('OFF',row['values'][-1])
        self.assertEqual(row['connection'].count('↔'),1)
        self.assertNotIn('연결 확인필요',row['values'][-3])
        self.assertEqual(self.snapshot(),before)
        self.s.toggle_assignment_exception(self.nodes[1],*self.slot(0,3))
        self.assertEqual(self.containing(self.slot(0))['values'][-3],'연결 / 집계 제외')
        self.set(0,3,'CORE-A','다른 이름','unknown')
        self.assertEqual(self.containing(self.slot(0))['values'][-3],'연결 / 예외')

    def test_conflicting_pair_keeps_both_ids_and_signal_error_visible(self):
        self.set(1,1,'OTHER','다른 내역','off');self.apply(1,'A\tB\n1\t1')
        row=self.containing(self.slot(0))
        self.assertEqual(row['values'][0],'CORE-A ↔ OTHER')
        self.assertEqual(row['values'][-3],'연결 확인필요');self.assertEqual(row['tag'],'summary_mismatch')
        self.assertIn('ON',row['values'][-1]);self.assertIn('OFF',row['values'][-1])

    def test_blank_and_temporary_labels_do_not_merge_unconnected_rows(self):
        for i,cid in enumerate(('', '임시-TEST'),2):
            self.set(0,i,cid,'참고','unknown');self.set(1,i,cid,'참고','unknown')
            self.assertNotEqual(self.containing(self.slot(0,i))['iid'],self.containing(self.slot(1,i))['iid'])

    def test_port_names_survive_numeric_cable_display(self):
        rn=self.s.add_node('RN',720,0,'rn')
        cable=self.s.add_cable(self.nodes[1],rn,'RN선','6C','기설')
        port='PORT:'+rn;row=self.s.cores(port)[0];idx=row['core_index'];label=row['label']
        self.s.update_core(port,idx,('PORT-ID','내부','normal','','on'))
        self.s.update_core(cable,2,('PORT-ID','내부','normal','','on'))
        rows=code['node_summary_rows'](self.s,rn,[('포트',port),('RN선',cable)])
        result=next(r for r in rows if (port,idx) in r['slots'])
        self.assertEqual(result['values'][2:4],(label,'2'))


def windows_ui():
    if sys.platform!='win32':return
    case=SummaryTests();case.setUp()
    try:
        (case.home/'ui').mkdir()
        case.set(1,1,'','','unknown');case.set(1,2,'CORE-A','GIS 내역','on')
        with patch.dict(os.environ,{'TELECOM_APP_HOME':str(case.home/'ui')}),patch.object(code['messagebox'],'showerror') as error,patch.object(code['messagebox'],'showinfo'):
            app=code['App']();app.store.close();app.store=case.s;errors=[]
            app.report_callback_exception=lambda *args:errors.append(str(args[1]))
            try:
                app.refresh();node=code['NodeDialog'](app,case.s,case.nodes[1])
                summary=code['NodeSummaryDialog'](node,case.s,case.nodes[1]);app.update()
                def select(slot):
                    iid=next(i for i,slots in summary.row_slots.items() if slot in slots)
                    summary.tree.selection_set(iid);app.update()
                    summary.slot_choice.current(summary._edit_slots.index(slot));summary.slot_choice.event_generate('<<ComboboxSelected>>');app.update()
                    return iid
                iid=select(case.slot(1,2));assert summary.selected_slot()==case.slot(1,2)
                summary.vars[1].set('아직 저장하지 않은 메모');before=case.snapshot()
                for _ in range(3):
                    summary.tree.cycle_sort('c1');app.update()
                    assert summary.tree.selection()==(iid,);assert summary.selected_slot()==case.slot(1,2)
                    assert summary.vars[1].get()=='아직 저장하지 않은 메모'
                summary.copy_table();copied=app.clipboard_get()
                assert '\t1\t2\t' in copied;assert '1번' not in copied;assert '2번' not in copied
                assert case.snapshot()==before
                # Editing the second cable must never silently target the first.
                summary.vars[0].set('RENAMED');summary.vars[4].set('OFF');summary.apply();app.update()
                assert case.s.core(*case.slot(0))['core_id']=='CORE-A'
                assert case.s.core(*case.slot(0))['signal']=='on'
                assert case.s.core(*case.slot(1,2))['core_id']=='RENAMED'
                assert case.s.core(*case.slot(1,2))['signal']=='off';assert case.splices()==[]
                assert summary.selected_slot()==case.slot(1,2)
                assert len([i for i in summary.row_slots if summary.tree.set(i,'id') in ('RENAMED','CORE-A')])==2
                case.s.undo();app.refresh();app.update()
                assert len([i for i in summary.row_slots if summary.tree.set(i,'id')=='CORE-A'])==1
                assert summary.selected_slot()==case.slot(1,2)
                assert summary.vars[1].get()=='아직 저장하지 않은 메모'
                summary.toggle_exception();app.update()
                import json
                exceptions=json.loads(case.s.node(case.nodes[1])['extra_json'])['assignmentExceptions']
                assert exceptions=={f'{case.cables[1]}::2':True}
                case.s.undo();case.apply(1,'A\tB\n1\t2');app.refresh();app.update()
                select(case.slot(1,2));summary.vars[4].set('OFF');summary.apply();app.update()
                assert case.s.core(*case.slot(0))['signal']=='off'
                assert case.s.core(*case.slot(1,2))['signal']=='off'
                assert case.s.core(*case.slot(2))['signal']=='on'
                case.s.undo();app.refresh();app.update()
                assert case.s.core(*case.slot(0))['signal']=='on'
                assert case.s.core(*case.slot(1,2))['signal']=='on'
                select(case.slot(1,2));case.s.set_node_locked(case.nodes[1],True);app.refresh();app.update()
                locked=case.snapshot();summary.vars[1].set('잠김 변경 금지');summary.apply();app.update()
                assert error.called;assert case.snapshot()==locked
                summary.copy_table();assert 'CORE-A' in app.clipboard_get()
                assert not errors,errors
                summary.destroy();node.destroy()
            finally:app.on_close()
        print('PASS Windows grouped numeric rows, clipboard, sorting/drafts, exact second-cable edits, local signals, undo regrouping and locked copy')
    finally:case.tearDown()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SummaryTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
