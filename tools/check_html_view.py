"""V207: 'HTML 화면으로 보기' opens the current drawing in a browser (read-only).

Checks that the HTML file carries the real drawing data (cables with the same
size colours / 신설 dash / 절단 stars / 철거 crosses, labels with 차수, node
badges), the core rows with 절단절체·코어절체 and completion, that the JSON is
safe inside <script>, and that making the view never changes the drawing."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_field_survey import code,wf


def embedded(text):
    match=re.search(r'<script id="data" type="application/json">(.*?)</script>',text,re.S)
    assert match,'data block missing'
    return json.loads(match.group(1))


class HtmlViewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();s=self.s=code['Store'](Path(self.temp.name)/'p.sqlite3')
        s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','before')");s.conn.commit()
        a=s.add_node('MDF',0,0);j=s.add_node('함체 J',240,0)
        self.f=s.add_cable(a,j,'F','12C','절단')
        s.update_core(self.f,1,('CORE-1','</script><b>내역','normal','','on'));s.update_core(self.f,2,('CORE-2','','normal','','on'))
    def tearDown(self):self.s.close();self.temp.cleanup()

    def test_core_rows_methods_and_completion(self):
        s=self.s
        work={'rows':[{'method':'절단절체','source_slots':[(self.f,1)]},{'method':'코어절체','current_slots':[[self.f,2]]},{'method':'','source_slots':[(self.f,3)]}]}
        report={'by_slot':{(self.f,1):{'required':True,'complete':True},(self.f,2):{'required':True,'complete':False,'reason':'경로 없음'},
                           (self.f,3):{'required':False,'excluded_reason':'OFF'}}}
        rows={r['n']:r for r in wf.html_view_cores(s,work,report)[self.f]}
        self.assertEqual(len(rows),12)
        self.assertEqual((rows[1]['id'],rows[1]['method'],rows[1]['done']),('CORE-1','절단절체',True))
        self.assertEqual((rows[2]['method'],rows[2]['done'],rows[2]['reason']),('코어절체',False,'경로 없음'))
        self.assertEqual((rows[3]['method'],rows[3]['done'],rows[3]['reason']),('',None,'OFF'))
        self.assertEqual(rows[4]['id'],'')
        print('PASS core rows carry cut/transfer method and done/not-done per core')

    def test_document_is_safe_and_read_only(self):
        s=self.s;before=s.conn.total_changes
        scene=dict(nodes=[],cables=[],labels=[],details=[],bounds=[0,0,10,10],cores=wf.html_view_cores(s),dashboard=wf.html_view_dashboard(s))
        text=wf.html_view_document(scene,dict(name='<도면>',kind='before',stage_label='현장반영',stages=list(wf.HTML_VIEW_STAGES)))
        self.assertNotIn('__DATA__',text);self.assertNotIn('__TITLE__',text)
        self.assertEqual(text.count('</script>'),2,'detail text must not close the data block')
        self.assertIn('&lt;도면&gt;',text)
        data=embedded(text)
        self.assertEqual(data['cores'][self.f][0]['detail'],'</script><b>내역')
        self.assertEqual(data['meta']['stages'][1][1],'현장반영')
        self.assertEqual(s.conn.total_changes,before,'building the view must not write to the drawing')
        self.assertNotIn('http://',text.replace('http://www.w3.org/2000/svg',''));self.assertNotIn('https://',text)
        print('PASS HTML view is offline, escapes drawing text and never writes')


def windows_ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    import faulthandler
    faulthandler.dump_traceback_later(180,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store;a=s.add_node('HTML A',380,220);b=s.add_node('HTML B',900,220);c=s.add_node('HTML C',900,520);d=s.add_node('HTML D',380,520)
            old=s.add_cable(a,b,'OLD','72C','절단',lot_no='1');new=s.add_cable(a,b,'NEW','72C','신설',lot_no='2')
            rem=s.add_cable(b,c,'REM','12C','철거',lot_no='3');keep=s.add_cable(a,d,'KEEP','144C','기설',lot_no='4')
            s.update_core(old,1,('HV-1','A','normal','','on'));s.update_core(new,1,('HV-1','A','normal','','on'))
            wf.set_cable_phase(s,[new],'1차작업')
            app.refresh();app.update()
            assert app.html_view_button.winfo_ismapped()
            before=s.conn.total_changes
            opened=[]
            with patch.object(code['webbrowser'],'open',lambda url:opened.append(url)):path=app.open_html_view()
            assert path and path.exists() and opened and opened[0].startswith('file:'),(path,opened)
            assert s.conn.total_changes==before
            data=embedded(path.read_text(encoding='utf-8'))
            cables={c['id']:c for c in data['cables']}
            assert set(cables)=={old,new,rem,keep},cables.keys()
            assert cables[new]['dash'] and not cables[old]['dash']
            assert cables[old]['marks'] and all(m[0]=='star' for m in cables[old]['marks'])
            assert cables[rem]['marks'] and all(m[0]=='x' for m in cables[rem]['marks'])
            assert cables[keep]['color']=='#e24a9b' and cables[rem]['color']=='#d32f2f' and cables[old]['color']=='#19703a'
            assert cables[old]['d']!=cables[new]['d'],'parallel cables keep separate paths'
            assert cables[new]['phases']==['1차'] and cables[old]['phases']==['1차'],(cables[new]['phases'],cables[old]['phases'])
            labels={l['id']:l for l in data['labels']}
            assert '[1차]' in labels[new]['parts'][0]['text'],labels[new]
            assert {n['name'] for n in data['nodes']}=={'HTML A','HTML B','HTML C','HTML D'}
            assert [r['id'] for r in data['cores'][old]][:1]==['HV-1'] and len(data['cores'][old])==72
            assert data['meta']['kind']==app.scenario_kind() and data['meta']['version']==code['APP_VERSION_LABEL']
            labels_menu=[app.file_menu.entrycget(i,'label') for i in range(app.file_menu.index('end')+1)]
            assert 'HTML 화면으로 보기' in labels_menu,labels_menu
            assert any(r['id']=='html_view' for r in app.drawing_tool_catalog())
            assert not errors,errors
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows HTML view button writes the real drawing (colours, marks, phases, cores) without changing it')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(HtmlViewTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
