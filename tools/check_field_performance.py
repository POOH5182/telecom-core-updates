"""Large field drawings: deterministic behavior and bounded repeated work."""
import cProfile
import hashlib
import json
import os
from pathlib import Path
import pstats
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from check_field_survey import code,wf


def drawing(folder,cables=60,capacity=144,used=48,connected=16):
    source=Path(folder)/'source.sqlite3';s=code['Store'](source)
    s.conn.execute("INSERT INTO meta VALUES('active_scenario','gis')")
    s.conn.executemany('INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?)',
        [(f'n{i:04}',f'함체 {i:04}',i*100,0,'hamche','','','{}') for i in range(cables+1)])
    s.conn.executemany('INSERT INTO cables VALUES(?,?,?,?,?,?,?,?)',
        [(f'c{i:04}',f'n{i:04}',f'n{i+1:04}',f'C{i:04}',capacity,f'{capacity}C','기설','{}') for i in range(cables)])
    s.conn.executemany('INSERT INTO cores VALUES(?,?,?,?,?,?,?)',
        [(f'c{i:04}',j,f'ID-{j:04}' if j<=used else '',f'회선 {j}' if j<=used else '',
          'normal' if j<=used else '','','on' if j<=connected else 'unknown') for i in range(cables) for j in range(1,capacity+1)])
    gis_pairs=[(f'n{i:04}',f'c{i-1:04}',j,f'c{i:04}',j) for i in range(1,cables) for j in range(1,used+1)]
    s.conn.executemany('INSERT INTO splices VALUES(?,?,?,?,?)',gis_pairs);s.conn.commit();s.close()
    target=Path(folder)/'field.sqlite3';wf.field_slot_copy(source,target);s=code['Store'](target)
    if connected:
        s.conn.executemany('INSERT INTO splices VALUES(?,?,?,?,?)',[p for p in gis_pairs if p[2]<=connected])
        value=wf.state(s);value['field_surveys']={}
        for i in range(1,cables):
            value['field_surveys'][f'n{i:04}']={'text':f'C{i-1:04}\tC{i:04}\n'+''.join(f'{j}\t{j}\n' for j in range(1,connected+1)),
                'overlay_mode':True,'overlay_policy':wf.FIELD_SLOT_POLICY,'corrections':[{'note':'보존된 현장 조사 이력','old_local':[{'cable_id':f'c{i:04}','core_index':j,'core_id':f'ID-{j:04}'} for j in range(1,used+1)]}]}
        wf.write_state(s,value,'성능 예시 도면',history=False)
        s.conn.execute("UPDATE cores SET core_id='OTHER' WHERE cable_id=? AND core_index=3",(f'c{cables//2:04}',));s.conn.commit()
    return s


def visible_data(store,node_id):
    return {'needs':{k:sorted(v) for k,v in store.node_assignment_needs(node_id).items()},
            'warning':store.node_warning_summary().get(node_id,{}),
            'checks':sorted((list(k),v) for k,v in wf.field_local_slots(store,node_id).items())}


def checksum(store,node_id):
    audit=wf.field_slot_audit(store);completion=wf.field_slot_completion(store)
    data={'components':[{k:c[k] for k in ('key','slots','real_ids','signals','required','coherent','confirmed','complete','reason','error','fingerprint')} for c in audit['components']],
          'completion':{k:v for k,v in completion.items() if k not in ('by_id','by_slot')},
          'id_index':{k:v['key'] for k,v in completion['by_id'].items()},
          'slot_index':{k:v['key'] for k,v in completion['by_slot'].items()},
          'cables':store.cable_core_warning_summary(),'view':visible_data(store,node_id)}
    def normalize(value):
        if isinstance(value,dict):return sorted(((normalize(k),normalize(v)) for k,v in value.items()),key=lambda x:json.dumps(x[0],ensure_ascii=False))
        if isinstance(value,(set,frozenset)):return sorted((normalize(v) for v in value),key=lambda x:json.dumps(x,ensure_ascii=False))
        if isinstance(value,(list,tuple)):return [normalize(v) for v in value]
        return value
    return hashlib.sha256(json.dumps(normalize(data),ensure_ascii=False).encode()).hexdigest()


def benchmark(cables=60,connected=16,profile=False):
    with tempfile.TemporaryDirectory() as folder:
        s=drawing(folder,cables=cables,connected=connected);node=f'n{cables//2:04}'
        try:
            timings={};prof=cProfile.Profile()
            if profile:prof.enable()
            for name,action in [('audit',lambda:wf.field_slot_audit(s)),('node_badges',s.node_warning_summary),
                                ('cable_badges',s.cable_core_warning_summary),('open_cold',lambda:visible_data(s,node)),
                                ('open_warm_10',lambda:[visible_data(s,node) for _ in range(10)])]:
                start=time.perf_counter();action();timings[name]=round(time.perf_counter()-start,6)
            if profile:
                prof.disable();pstats.Stats(prof).strip_dirs().sort_stats('cumtime').print_stats(22)
            result={'cables':cables,'capacity':144,'used_per_cable':48,'connected_per_cable':connected,'seconds':timings,'checksum':checksum(s,node)}
            print(json.dumps(result,ensure_ascii=False));return result
        finally:s.close()


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.s=drawing(self.temp.name,cables=6,capacity=12,used=6,connected=2)
    def tearDown(self):self.s.close();self.temp.cleanup()

    def test_v73_confirmations_survive_cache_optimization_and_recheck_after_edit_undo(self):
        s=self.s;slot=('c0000',1);audit=wf.field_slot_audit(s)
        # Golden signatures produced by the released V73 implementation.
        signatures={('c0000',1):'f9f4497f9eb9fe87af4b9d6f92e6f9cfbee236305d093e6dc68ae0bf30da87c0',
                    ('c0000',4):'afb7f7b6fc2289c2864a92190a1f5f16b072e9e3c0bd412771b9fd139932f7bc',
                    ('c0003',3):'e50f28789d66e512e363571eef4e5f534d657a479df250b9da530e83bcd55463'}
        for pos,signature in signatures.items():
            self.assertEqual(wf.field_slot_signature(s,audit['by_slot'][pos]['slots'],audit_rows=audit['rows'],net=audit['net']),signature)
        value=wf.state(s);value['field_slot_confirmations']=[{'slots':audit['by_slot'][slot]['slots'],'signature':signatures[slot]}]
        wf.write_state(s,value,'기존 확정 불러오기')
        self.assertTrue(wf.field_slot_audit(s)['by_slot'][slot]['complete'])
        self.assertEqual(wf.field_local_slots(s,'n0003')[('c0002',1)],'OK')
        s.update_core('c0002',1,('ID-0001','회선 1','normal','','off'))
        self.assertFalse(wf.field_slot_audit(s)['by_slot'][slot]['complete'])
        self.assertEqual(wf.field_local_slots(s,'n0003')[('c0002',1)],'NOT OK')
        s.undo();self.assertTrue(wf.field_slot_audit(s)['by_slot'][slot]['complete'])
        self.assertEqual(wf.field_local_slots(s,'n0003')[('c0002',1)],'OK')
        s.redo();self.assertFalse(wf.field_slot_audit(s)['by_slot'][slot]['complete'])

    def test_one_report_serves_both_summaries_and_panes_without_leaking_drafts(self):
        s=self.s;node='n0003';calls=[];original=wf.FieldSurvey.report
        def counted(engine,*args,**kwargs):calls.append(engine.node_id);return original(engine,*args,**kwargs)
        with patch.object(wf.FieldSurvey,'report',counted):
            for _ in range(4):
                wf.field_summary(s,node);wf.field_local_summary(s,node);wf.field_local_slots(s,node)
            self.assertEqual(calls,[node])
            saved=wf.field_display_rows(s,node);records=wf.field_records(s)
            records[node]['text']='C0002\tC0003\n6\t6'
            self.assertIs(wf.field_display_rows(s,node),saved)
            draft=wf.field_display_rows(s,node,records[node]);self.assertIsNot(draft,saved)
            self.assertEqual(wf.field_display_rows(s,node),saved)
            self.assertEqual(len(calls),3)
            old=wf.field_read_state(s);s.update_core('c0002',2,('ID-0002','변경 이름','normal','','unknown'))
            self.assertIsNot(wf.field_read_state(s),old)
            self.assertIsNot(wf.field_display_rows(s,node),saved)
            # A scenario replacement may have the same DB revision and change
            # count; the generation must still invalidate all read-only views.
            cached=wf.field_display_rows(s,node);s._view_generation+=1
            self.assertIsNot(wf.field_display_rows(s,node),cached)

    def test_many_signatures_do_not_rescan_all_splices_or_cables(self):
        class Splices(list):
            passes=0
            def __iter__(self):self.passes+=1;return super().__iter__()
        class Cables(dict):
            passes=0
            def values(self):self.passes+=1;return super().values()
        s=self.s;audit=wf.field_slot_audit(s);net=wf.Network(s.conn)
        net.splices=Splices(net.splices);net.cables=Cables(net.cables)
        for _ in range(5):
            for comp in audit['components']:wf.field_slot_signature(s,comp['slots'],audit_rows=audit['rows'],net=net)
        self.assertLessEqual(net.splices.passes,1)
        self.assertLessEqual(net.cables.passes,1)


def windows_dialogs():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as folder:
        os.environ['TELECOM_APP_HOME']=folder;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showinfo',return_value=None), \
             patch.object(code['messagebox'],'askyesno',return_value=True), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *a:errors.append(str(a))
            try:
                fixture=drawing(folder,cables=80);path=fixture.path;fixture.close()
                app.replace_current_from(path);app.deiconify();app.update();s=app.store
                calls=[];original=wf.FieldSurvey.report
                def counted(engine,*args,**kwargs):calls.append(engine.node_id);return original(engine,*args,**kwargs)
                timings=[]
                with patch.object(wf.FieldSurvey,'report',counted),patch.object(s,'trace_context',wraps=s.trace_context) as trace:
                    for i in range(35,40):
                        start=time.perf_counter();node=code['open_detail_dialog'](app,s,'node',f'n{i:04}');app.update()
                        timings.append(time.perf_counter()-start)
                    assert trace.call_count==0,'Opening with no selected core rebuilt the global trace'
                    assert calls==[],calls
                    owners=list(node.by_label)
                    node.left_var.set(owners[0]);node.right_var.set(owners[1]);node.reload_all();app.update()
                    assert len(node.left_tree.get_children())==144 and len(node.right_tree.get_children())==144
                    assert calls==[],calls
                    node.left_tree.selection_set('1');app.update();assert trace.call_count>0
                    assert app.highlight_cables
                    count=trace.call_count;node.left_tree.selection_remove(*node.left_tree.selection());app.update()
                    assert trace.call_count==count
                    node.destroy()
                assert not errors,errors
                print('PASS Windows V74 80-cable field drawing: five enclosure opens and 144-core panes reused checks, no unused trace build; selected core still highlights. Open seconds: '+json.dumps([round(t,4) for t in timings]))
            finally:app.on_close()


if __name__=='__main__':
    if '--check' in sys.argv:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PerformanceTests))
        if not result.wasSuccessful():raise SystemExit(1)
        windows_dialogs()
    else:
        benchmark(cables=int(sys.argv[1]) if len(sys.argv)>1 and sys.argv[1].isdigit() else 60,
                  connected=0 if '--empty' in sys.argv else 16,profile='--profile' in sys.argv)
