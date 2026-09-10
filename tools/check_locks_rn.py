"""V59 lock migration, immutable connections, RN endpoints and real copy/field UI."""
import json
import os
from legacy_field_fixture import existing_field
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
code=runpy.run_path(str(ROOT/'app'/'telecom_core_app.pyw'),run_name='locks_rn_check')
wf=code['App'].__init__.__globals__['workflow']


class LocksRNTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'drawing.sqlite3'
        self.store=code['Store'](self.path);s=self.store
        s.conn.execute("INSERT INTO meta VALUES('active_scenario','before')");s.conn.commit()
        self.a=s.add_node('말단 함체',0,0);self.rn=s.add_node('RN',240,0,node_type='rn')
        self.cable=s.add_cable(self.a,self.rn,'CABLE','6C','기설')
        s.ensure_ports(self.rn,{'mp':1,'sp':1,'p':1})
    def tearDown(self):self.store.close();self.temp.cleanup()
    def used(self,index=1):
        self.store.update_core(self.cable,index,(f'ID-{index}',f'내역 {index}','normal','','off'))
    def inspect(self,index=1):return wf.Network(self.store.conn).inspect(f'ID-{index}',wf.DEFAULTS)

    def test_rn_legacy_terminal_flag_does_not_end_unconnected_cable(self):
        s=self.store;self.used()
        with s.action('구버전 RN 말단 설정'):
            s.conn.execute("UPDATE nodes SET extra_json=json_set(extra_json,'$.terminal',1) WHERE id=?",(self.rn,))
        self.assertFalse(wf.cable_terminal(s.node(self.rn),1))
        self.assertFalse(wf.assignment_terminal(s.node(self.rn),1))
        self.assertFalse(self.inspect()['complete'])
        self.assertEqual(s.drawing_connection_progress()['done'],0)
        self.assertIn(1,s.node_assignment_needs(self.rn)[self.cable])
        self.assertTrue(s.node_warning_summary()[self.rn]['rn_in'])
        self.assertTrue(s.trace_core_paths('ID-1')['issues'])

    def test_every_connected_rn_internal_port_is_a_valid_endpoint(self):
        s=self.store
        for index,port in enumerate(s.cores('PORT:'+self.rn),1):
            self.used(index);s.connect(self.rn,(self.cable,index),('PORT:'+self.rn,port['core_index']))
            self.assertTrue(self.inspect(index)['complete'],self.inspect(index))
            self.assertFalse(s.trace_core_paths(f'ID-{index}')['issues'])
        self.assertEqual(s.drawing_connection_progress()['done'],4)
        self.assertFalse(s.node_assignment_needs(self.rn))
        self.assertFalse(s.node_warning_summary().get(self.rn,{}).get('rn_in'))
        self.assertEqual(s.cable_core_warning_summary()[self.cable]['unassigned'],0)
        with s.action('RN 내부 접속 해제'):
            s.conn.execute('DELETE FROM splices WHERE node_id=? AND cable1_id=? AND core1_index=1',(self.rn,self.cable))
        self.assertFalse(self.inspect()['complete'])
        self.assertEqual(s.drawing_connection_progress()['done'],3)

    def test_rn_field_ports_apply_undo_and_terminal_enclosure_exclusion(self):
        s=self.store;self.used();old=wf.plan_snapshot(s.conn)
        self.assertFalse(wf.field_required(s,s.node(self.a)))
        self.assertEqual(wf.field_summary(s,self.a)['total'],0)
        self.assertTrue(wf.field_required(s,s.node(self.rn)))
        self.assertTrue(s.node_warning_summary()[self.rn]['field']['pending'])
        self.assertNotIn('field',s.node_warning_summary().get(self.a,{}))
        self.assertEqual({r['node_id'] for r in wf.field_check_rows(s)},{self.rn})
        engine=wf.FieldSurvey(s,self.rn);engine.save('CABLE\tRN내부\n1\tP1')
        self.assertEqual(wf.plan_snapshot(s.conn),old)
        row=wf.FieldSurvey(s,self.rn).report()[0];self.assertEqual((row['status'],row['comparison']),('미확인','신규'))
        before=wf.plan_snapshot(s.conn);preview=wf.field_preview(s,self.rn,{row['key']})
        self.assertEqual(wf.plan_snapshot(s.conn),before)
        wf.field_apply(s,self.rn,preview['keys'],preview['revision'],preview['generation'])
        self.assertTrue(self.inspect()['complete'])
        self.assertEqual(wf.field_summary(s,self.rn)['done'],1)
        self.assertFalse(wf.field_check_rows(s))
        s.undo();self.assertEqual(wf.plan_snapshot(s.conn),before)
        self.assertFalse(self.inspect()['complete']);s.redo();self.assertTrue(self.inspect()['complete'])
        # Port renumber/name input uses the actual port index and does not treat
        # an unconnected RN as a single-column terminal observation.
        self.assertTrue(wf.FieldSurvey(s,self.rn).parse('CABLE\n1')[0]['errors'])
        with s.action('연결된 코어ID 전체 변경'):
            for table in ('cores','ports'):s.conn.execute(f"UPDATE {table} SET core_id='CHANGED' WHERE core_id='ID-1'")
        self.assertEqual(wf.field_summary(s,self.rn)['done'],0)
        self.assertTrue(wf.field_check_rows(s))

    def test_explicit_terminal_enclosure_is_exempt_even_with_two_cables(self):
        s=self.store;b=s.add_node('끝',400,0);s.add_cable(self.a,b,'EXTRA','6C','기설');self.used()
        self.assertTrue(wf.field_required(s,s.node(self.a)))
        s.set_node_terminal(self.a,True)
        self.assertFalse(wf.field_required(s,s.node(self.a)))
        self.assertFalse(any(r['node_id']==self.a for r in wf.field_check_rows(s)))
        self.assertNotIn('field',s.node_warning_summary().get(self.a,{}))

    def test_cable_auto_lock_migration_reopen_unlock_and_atomic_protection(self):
        s=self.store;b=s.add_node('상대 함체',400,0);c=s.add_cable(self.a,b,'LOCK','6C','기설')
        s.update_core(c,1,('LOCK-ID','보존','normal','','off'))
        s.set_node_locked(self.a,True);self.assertFalse(wf.cable_locked(s,c))
        self.assertFalse(wf.cable_locked(s,self.cable)) # RN never counts as a locked enclosure.
        # Simulate the older cable UPDATE trigger; schema upgrade must replace it.
        s.conn.execute('DROP TRIGGER enclosure_lock_cables_UPDATE')
        s.conn.execute("CREATE TRIGGER enclosure_lock_cables_UPDATE BEFORE UPDATE ON cables BEGIN SELECT RAISE(ABORT,'old lock'); END")
        s.conn.commit();s.close();self.store=code['Store'](self.path);s=self.store
        s.set_cable_lot_no(c,'ONE-LOCK-OK')
        with self.assertRaises(ValueError):s.resize_cable(c,'12C')
        with self.assertRaises(ValueError):s.update_core(c,1,('MODIFIED','보존','normal','','off'))
        s.set_node_locked(b,True);self.assertTrue(wf.cable_locked(s,c))
        before=wf.plan_snapshot(s.conn)
        with self.assertRaises(ValueError):
            with s.action('다중 케이블 변경'):
                s.set_cable_lot_no(self.cable,'ROLLBACK')
                s.set_cable_lot_no(c,'BLOCKED')
        self.assertEqual(wf.plan_snapshot(s.conn),before)
        s.close();self.store=code['Store'](self.path);s=self.store;self.assertTrue(wf.cable_locked(s,c))
        s.set_node_locked(b,False);self.assertFalse(wf.cable_locked(s,c))
        s.set_cable_lot_no(c,'UNLOCKED');self.assertEqual(code['cable_lot_no'](s.cable(c)),'UNLOCKED')
        s.undo();s.undo();self.assertTrue(wf.cable_locked(s,c));s.redo();self.assertFalse(wf.cable_locked(s,c))


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showwarning',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showinfo',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=False), \
             patch.object(code['messagebox'],'askyesno',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *args:errors.append(str(args))
            try:
                s=app.store;a=s.add_node('복사 함체',0,0);b=s.add_node('상대 함체',240,0)
                s.set_node_details(a,'복사 함체',hamche=('12C','HC-001'))
                cable=s.add_cable(a,b,'COPY-CABLE','6C','기설',lot_no='LOT-001')
                s.update_core(cable,1,('COPY-ID','복사 내역','normal','','off'))
                nd=code['NodeDialog'](app,s,a);cd=code['CableDialog'](app,s,cable);pd=code['NodePropertiesDialog'](app,s,a)
                app.update();s.set_node_locked(a,True);s.set_node_locked(b,True);app.refresh();app.update()
                assert str(nd.name_entry.cget('state'))=='readonly'
                assert str(cd.id_entry.cget('state'))=='readonly'
                assert '자동 잠금' in cd.lock_notice.cget('text')
                assert any('🔒' in p['text'] for entry in app.current_label_layout for p in entry['parts'])
                def copied(entry,value):
                    entry.winfo_toplevel().lift();entry.focus_force();app.update()
                    entry.event_generate('<Control-a>');entry.event_generate('<Control-c>');app.update()
                    assert app.clipboard_get()==value,(app.clipboard_get(),value)
                    entry.event_generate('<BackSpace>');entry.insert(0,'DENIED');app.update()
                    assert entry.get()==value
                copied(nd.name_entry,'복사 함체');copied(cd.id_entry,'COPY-CABLE');copied(cd.lot_entry,'LOT-001')
                for window in (nd,pd):
                    stack=list(window.winfo_children());entries=[]
                    while stack:
                        w=stack.pop();stack.extend(w.winfo_children())
                        if isinstance(w,code['ttk'].Entry) and w.get()=='HC-001':entries.append(w)
                    assert entries
                    copied(entries[0],'HC-001')
                cd.notebook.select(cd.identity_tab);app.update();cd.identity_tree.selection_set('1')
                cd.copy_identity_cell();assert app.clipboard_get()=='COPY-ID'
                s.set_node_locked(b,False);app.refresh();app.update()
                assert str(cd.id_entry.cget('state'))=='normal'
                assert str(nd.name_entry.cget('state'))=='readonly'
                s.set_node_locked(a,False);app.refresh();app.update()
                assert str(nd.name_entry.cget('state'))=='normal'
                for window in (nd,cd,pd):window.destroy()
                # Removed items must not reappear from a saved custom catalog.
                state=wf.state(s);state['annotation_catalog']=['경로다름','접속 확인','현장확인','절체 예정','유지항목'];wf.write_state(s,state)
                dialog=wf.AnnotationDialog(app,s,(cable,1),lambda:None)
                assert all(wf.active_status_label(v) for v in dialog.catalog)
                assert '유지항목' in dialog.catalog;dialog.destroy()
                # Real RN survey entry and badge; automatic enclosure ends do not gate after work.
                r=s.add_node('현장 RN',400,200,node_type='rn');end=s.add_node('말단 함체',240,200)
                rc=s.add_cable(end,r,'RN-CABLE','6C','기설');s.ensure_ports(r,{'mp':1,'sp':0,'p':1})
                s.update_core(rc,1,('RN-ID','RN 내역','normal','','off'));s.connect(r,(rc,1),('PORT:'+r,3))
                assert (existing_field(app) or app.load_scenario('before'));s=app.store
                nd=code['NodeDialog'](app,s,r);nd.field_survey_open();app.update()
                fd=next(w for w in nd.winfo_children() if isinstance(w,wf.FieldSurveyDialog))
                assert 'RN내부' in fd.sheet.get_text()
                fd.clipboard_clear();fd.clipboard_append('RN-CABLE\tRN내부\n1\tP1');fd.sheet.paste_from_a1();fd.inspect();app.update()
                assert s.node_warning_summary()[r]['field']['done']==1
                assert 'field' not in s.node_warning_summary().get(end,{})
                assert not wf.field_check_rows(s)
                fd.destroy();nd.destroy();assert not errors,errors
            finally:app.on_close()
    print('PASS Windows locked name/ID/LOT Ctrl+C, mutation denial, live cable lock/unlock, status removal and RN internal field survey')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LocksRNTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS V59 RN internal endpoints, field scope, lock migration and atomic protection')
