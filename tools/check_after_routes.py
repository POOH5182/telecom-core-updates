"""Cable-only step 1: exact minimum paths, manual choices and durable decisions."""
import copy
import csv
import os
from legacy_field_fixture import existing_field
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_after_plan import code,wf,LocalApp,update


def drawing(app):
    s=app.store
    a=s.add_node('시작',0,150);b=s.add_node('왼쪽 끊김',180,150);c=s.add_node('오른쪽 끊김',500,150);d=s.add_node('끝',680,150);x=s.add_node('우회',340,330)
    left=s.add_cable(a,b,'LEFT','12C','기설');cut=s.add_cable(b,c,'OLD-CUT','12C','기설');right=s.add_cable(c,d,'RIGHT','12C','기설')
    update(s,left,1,dict(core_id='CORE-1',detail='첫 회선',signal='on'))
    s.connect(b,(left,1),(cut,1));s.connect(c,(cut,1),(right,1))
    s.backup_to(app.scenario_path('before'))
    with s.action('후도면 절단 시험'):s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(cut,))
    direct=s.add_cable(b,c,'DIRECT','12C','신설');detour1=s.add_cable(b,x,'DETOUR-1','12C','신설');detour2=s.add_cable(x,c,'DETOUR-2','12C','신설')
    return dict(a=a,b=b,c=c,d=d,x=x,left=left,cut=cut,right=right,direct=direct,detour1=detour1,detour2=detour2)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store;self.ids=drawing(self.app);self.service=wf.AfterRoutePlanner(self.app)
    def tearDown(self):self.s.close();self.temp.cleanup()
    def problem(self,cid='CORE-1'):
        row=next(r for r in self.service.summary()['rows'] if r['core_id']==cid);return self.service.problem(row['key'])
    def physical(self):return wf.plan_snapshot(self.s.conn)
    def before(self):return self.app.scenario_path('before').read_bytes()
    def manual(self):
        i=self.ids
        return dict(nodes=[i[k] for k in ('a','b','x','c','d')],cables=[i[k] for k in ('left','detour1','detour2','right')],endpoints=[i['a'],i['d']],source='직접 지정')

    def test_recommendation_is_minimum_preserves_fragments_and_never_allocates(self):
        original=self.physical();before=self.before();history=self.s.history_rows();state=wf.plan_settings(self.s)
        p=self.problem();self.assertEqual(len(p['components']),2)
        route=self.service.recommend(p);self.assertTrue(route['ok'],route)
        self.assertEqual(route['added'],1);self.assertEqual(set(route['cables']),{self.ids[k] for k in ('left','direct','right')})
        self.assertNotIn(self.ids['cut'],route['cables']);self.assertEqual(route['nodes'][0],p['default_ends'][0])
        self.assertEqual(self.service.recommend(p),route)
        self.assertEqual((self.physical(),self.before(),self.s.history_rows(),wf.plan_settings(self.s)),(original,before,history,state))
        self.service.save(p,route,'ok');self.assertTrue(self.service.summary()['ready'])
        self.assertEqual((self.physical(),self.before()),(original,before))
        self.assertFalse(wf.completion_report(self.s,'after')['by_id']['CORE-1']['complete'])
        self.assertEqual(self.s.core(self.ids['direct'],1)['core_id'],'')

    def test_nok_manual_detour_draft_reopen_undo_and_cloud(self):
        p=self.problem();route=self.service.recommend(p);original=self.physical();self.service.save(p,route,'nok')
        self.assertEqual(self.problem()['record']['state'],'nok');self.assertFalse(self.service.summary()['ready'])
        route=self.manual();draft=dict(route,nodes=route['nodes'][:3],cables=route['cables'][:2])
        self.service.save(self.problem(),draft,'draft');state=copy.deepcopy(wf.plan_settings(self.s))
        path=self.s.path;self.s.close();self.app.store=code['Store'](path);self.s=self.app.store;self.service=wf.AfterRoutePlanner(self.app)
        self.assertEqual(wf.plan_settings(self.s),state);self.assertEqual(self.problem()['record']['cables'],draft['cables'])
        before=copy.deepcopy(wf.plan_settings(self.s));self.service.save(self.problem(),route,'ok')
        self.assertTrue(self.service.summary()['ready']);saved=copy.deepcopy(wf.plan_settings(self.s))
        self.assertTrue(self.problem()['record']['rejected']['cables']);self.assertEqual(self.physical(),original)
        self.s.undo();self.assertEqual(wf.plan_settings(self.s),before);self.s.redo();self.assertEqual(wf.plan_settings(self.s),saved)
        folder=Path(self.temp.name)/'scenarios';folder.mkdir();self.s.backup_to(folder/'after.sqlite3')
        bundle=wf.cloud_unpack(wf.cloud_bundle(self.s,folder));other=Path(self.temp.name)/'other.sqlite3';other.write_bytes(bundle['working.sqlite3'])
        store=code['Store'](other)
        try:self.assertEqual(wf.plan_settings(store),saved)
        finally:store.close()

    def test_manual_validation_rejects_broken_missing_loop_and_retired_paths(self):
        p=self.problem();route=self.manual();original=self.physical();settings=wf.plan_settings(self.s)
        cases=[dict(route,cables=[self.ids['left'],self.ids['detour2'],self.ids['right']],nodes=[self.ids[k] for k in ('a','b','c','d')]),
               dict(route,cables=[self.ids['left'],self.ids['cut'],self.ids['right']],nodes=[self.ids[k] for k in ('a','b','c','d')]),
               dict(route,cables=route['cables'][:-1],nodes=route['nodes'][:-1]),
               dict(route,cables=[self.ids[k] for k in ('left','detour1','detour1','direct','right')],nodes=[self.ids[k] for k in ('a','b','x','b','c','d')])]
        for candidate in cases:
            with self.subTest(path=candidate['cables']):
                with self.assertRaises(ValueError):self.service.save(p,candidate,'ok')
        self.assertEqual(self.physical(),original);self.assertEqual(wf.plan_settings(self.s),settings)

    def test_id_only_target_policy_dedup_and_missing_before_identity(self):
        i=self.ids
        for index,cid,status,signal in ((2,'CANCEL','cancel','on'),(3,'임시-OFF','','off'),(4,'임시-ON','','on'),(5,'EXPECTED','cancel_expected','off'),(6,'EXCEPTION','exception','off')):
            update(self.s,i['left'],index,dict(core_id=cid,status1=status,signal=signal))
        update(self.s,i['left'],7,dict(core_id='',signal='on'))
        rows=self.service.summary()['rows'];ids=[r['core_id'] for r in rows]
        self.assertEqual(ids.count('CORE-1'),1);self.assertNotIn('CANCEL',ids);self.assertNotIn('임시-OFF',ids)
        self.assertTrue({'임시-ON','EXPECTED','EXCEPTION',''}.issubset(ids))
        empty=next(r for r in rows if not r['core_id']);self.assertFalse(self.service.recommend(empty['problem'])['ok'])
        with self.s.action('현재 선번만 제거'):
            self.s.conn.execute("DELETE FROM splices");self.s.conn.execute("UPDATE cores SET core_id='',detail='',signal='' WHERE core_id='CORE-1'")
        p=self.problem();self.assertFalse(p['components']);self.assertTrue(p['default_ends'])
        self.assertTrue(self.service.recommend(p)['ok'])

    def test_stale_decisions_recheck_graph_but_names_and_other_decisions_do_not(self):
        p=self.problem();route=self.service.recommend(p)
        with self.s.action('이름만 변경'):self.s.conn.execute("UPDATE cores SET detail='변경명' WHERE core_id='CORE-1'")
        with self.assertRaisesRegex(ValueError,'변경'):self.service.save(p,route,'ok')
        p=self.problem();self.service.save(p,self.service.recommend(p),'ok')
        with self.s.action('도면 배치와 이름 변경'):
            self.s.conn.execute("UPDATE cores SET detail='다른 표시명' WHERE core_id='CORE-1'")
            self.s.conn.execute('UPDATE nodes SET x=x+10')
        self.assertTrue(self.problem()['saved_ok'])
        data=wf.plan_settings(self.s);data['route_step']['decisions']['other-test']={'state':'nok'};wf.plan_save(self.s,data,'다른 코어 계획')
        self.assertTrue(self.problem()['saved_ok'])
        self.s.add_cable(self.ids['b'],self.ids['c'],'NEWER','12C','신설')
        self.assertFalse(self.problem()['saved_ok']);self.assertEqual(self.service.summary()['rows'][0]['status'],'재확인')

    def test_no_path_and_search_limit_never_claim_minimum_or_confirm(self):
        p=self.problem();self.assertTrue(self.service.recommend(p,limit=1)['limited'])
        with self.s.action('모든 대안 철거'):
            for key in ('direct','detour1'):self.s.conn.execute("UPDATE cables SET status='철거' WHERE id=?",(self.ids[key],))
        result=self.service.recommend(self.problem());self.assertFalse(result['ok']);self.assertIn('없습니다',result['reason'])
        self.assertFalse(self.service.summary()['ready'])

    def test_three_components_are_all_included_not_just_nearest_pair(self):
        i=self.ids;y=self.s.add_node('중간1',270,-120);z=self.s.add_node('중간2',410,-120)
        middle=self.s.add_cable(y,z,'MIDDLE','12C','기설');update(self.s,middle,1,dict(core_id='CORE-1'))
        in_c=self.s.add_cable(i['b'],y,'M-IN','12C','신설');out_c=self.s.add_cable(z,i['c'],'M-OUT','12C','신설')
        p=self.problem();self.assertEqual(len(p['components']),3);route=self.service.recommend(p)
        self.assertTrue(route['ok'],route);self.assertEqual(route['added'],2)
        self.assertEqual(set(route['cables']),{i['left'],middle,i['right'],in_c,out_c})
        self.assertNotIn(i['direct'],route['cables'])
        self.service.save(p,route,'ok');self.assertTrue(self.service.summary()['ready'])

    def test_existing_spliced_component_cannot_be_shortcut_and_rn_is_endpoint(self):
        i=self.ids;y=self.s.add_node('연결 유지',-160,150);extension=self.s.add_cable(y,i['a'],'EXT','12C','기설')
        self.s.connect(i['a'],(extension,1),(i['left'],1));self.s.add_cable(y,i['b'],'SHORTCUT','12C','신설')
        p=self.problem();route=self.service.recommend(p,[y,i['d']]);self.assertTrue(route['ok'],route)
        self.assertIn(extension,route['cables']);self.assertIn(i['left'],route['cables'])
        rn=self.s.add_node('RN',900,150,'rn');rn_cable=self.s.add_cable(i['d'],rn,'RN-CABLE','12C','신설')
        p=self.problem();result=self.service.recommend(p,[y,rn]);self.assertTrue(result['ok'],result);self.assertEqual(result['nodes'][-1],rn)
        self.assertIn(rn_cable,result['cables'])
        # Step 1 may plan to RN, but never allocates an internal port.
        original=self.physical();self.service.save(p,result,'ok');self.assertEqual(self.physical(),original)

    def test_duplicate_actual_ids_and_locks(self):
        i=self.ids;self.s.set_node_locked(i['b'],True);p=self.problem();original=self.physical()
        self.service.save(p,self.service.recommend(p),'ok');self.assertEqual(self.physical(),original)
        self.s.set_node_locked(i['b'],False)
        update(self.s,i['left'],8,dict(core_id='CORE-1'))
        result=self.service.recommend(self.problem());self.assertFalse(result['ok']);self.assertIn('여러 코어',result['reason'])


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showinfo',return_value=None), \
             patch.object(code['messagebox'],'askyesno',return_value=True), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *args:errors.append(str(args))
            try:
                # Exercise an existing V71 field snapshot through before -> after.
                s=app.store;a=s.add_node('준비 A',0,0);b=s.add_node('준비 B',100,0);c=s.add_cable(a,b,'PREP','12C','기설')
                update(s,c,1,dict(core_id='PREP-ID',signal='off'));assert (existing_field(app) or app.load_scenario('before'))
                app.save_current_drawing(silent=True);assert app.load_scenario('after')
                i=drawing(app);s=app.store;original=wf.plan_snapshot(s.conn);before=app.scenario_path('before').read_bytes()
                dialog=wf.AfterPlanDialog(app);app.update();panel=dialog.route_panel
                assert dialog.tabs.tab(dialog.tabs.select(),'text')=='1 케이블 경로'
                row_id=next(k for k,r in panel.visible.items() if r['core_id']=='CORE-1');panel.cores.selection_set(row_id);app.update()
                assert panel.draft['ok'] and panel.draft['added']==1
                assert len(panel.problem['components'])==2
                assert i['direct'] in panel.draft['cables'];assert app.highlight_owner is dialog
                assert panel.ok_button.winfo_viewable() and panel.map.winfo_height()>80
                assert panel.ok_button.winfo_rooty()+panel.ok_button.winfo_height()<=dialog.winfo_rooty()+dialog.winfo_height()
                # Sorting preserves the selected identity and its recommendation.
                panel.cores.cycle_sort('1');app.update();assert panel.problem['core_id']=='CORE-1'
                panel.reject();app.update();assert panel.mode=='직접 지정';assert panel.problem['record']['state']=='nok'
                # Select a complete longer route with the real map-click handler.
                order=['left','detour1','detour2','right'] if panel.draft['nodes'][0]==i['a'] else ['right','detour2','detour1','left']
                for key in order:panel.map_click(i[key]);app.update()
                assert panel.problem['record']['state']=='draft';assert str(panel.ok_button['state'])=='normal'
                assert set(panel.draft['cables'])=={i[k] for k in order}
                panel.back();app.update();assert str(panel.ok_button['state'])=='disabled'
                panel.map_click(i[order[-1]]);app.update();panel.accept();app.update()
                saved=next(r for r in panel.report['rows'] if r['core_id']=='CORE-1');assert saved['complete']
                assert saved['problem']['record']['source']=='직접 지정'
                assert wf.plan_snapshot(s.conn)==original;assert app.scenario_path('before').read_bytes()==before
                path=Path(temp)/'routes.csv'
                dialog.tabs.select(dialog.pages['1 케이블 경로'])
                with patch.object(wf.filedialog,'asksaveasfilename',return_value=str(path)):dialog.export_table()
                with path.open(encoding='utf-8-sig',newline='') as handle:exported=list(csv.DictReader(handle))
                exported_core=next(r for r in exported if r['코어ID']=='CORE-1')
                # New cables receive the app's existing NEW1/NEW2 user-facing IDs.
                assert exported_core['케이블 순서']==' → '.join(s.cable(i[k])['cable_id'] for k in order)
                assert exported_core['지정 방법']=='직접 지정'
                dialog.destroy();app.update();assert not app.highlight_cables
                reopened=wf.AfterPlanDialog(app);app.update();panel=reopened.route_panel
                row_id=next(k for k,r in panel.visible.items() if r['core_id']=='CORE-1');panel.cores.selection_set(row_id);app.update()
                assert panel.mode=='확정' and panel.problem['saved_ok'];assert set(panel.draft['cables'])=={i[k] for k in order}
                assert not errors,errors # Leave the workbench open to exercise whole-app shutdown.
            finally:app.on_close()
    print('PASS Windows step 1 core list, minimum recommendation, sorting, NOK, ordered map-click detour, draft/back/OK, CSV, reopen and no allocation')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RouteTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS minimum additional-cable paths, all fragments, NOK/manual decisions, no core allocation, stale guards, history and cloud persistence')
