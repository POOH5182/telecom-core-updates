"""V166: 신호 섞임 helpers - per-cable ON/OFF on a mixed route, a mixed-core list,
a warning before a signal edit makes a path mixed, and OFF kept on empty numbers."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_field_survey import code,wf
from check_temporary_route_rename import fixture


def real_path(s,cables,signals):
    with s.action('synthetic real path'):
        for c,signal in zip(cables,signals):
            s.conn.execute("UPDATE cores SET core_id='REAL-1',detail='실코어',status1='normal',signal=? WHERE cable_id=? AND core_index=1",(signal,c))
        s.conn.execute("UPDATE cores SET core_id='',detail='',signal='unknown' WHERE cable_id=? AND core_index=6",(cables[0],))


class SignalMix(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
    def tearDown(self):self.s.close();self.temp.cleanup()

    def open(self,field,signals=('on','unknown','off')):
        self.s,self.n,self.c=fixture(self.home/('f.sqlite3' if field else 'p.sqlite3'),field);real_path(self.s,self.c,signals)
        return self.s

    def snapshot(self):return [tuple(r) for r in self.s.conn.execute('SELECT * FROM cores ORDER BY cable_id,core_index')]+[tuple(r) for r in self.s.conn.execute('SELECT * FROM splices ORDER BY 1,2,3')]

    def test_mixed_route_marks_each_cable(self):
        for field in (True,False):
            with self.subTest(field=field):
                s=self.open(field);before=self.snapshot()
                model=wf.core_connection_highlight(s,[(self.c[0],1)])
                row=next(r for r in model['legend'] if r['kind']=='segment')
                self.assertEqual(row['signal'],'mixed',row)
                self.assertEqual(row['cable_signals'],{self.c[0]:'on',self.c[1]:'unknown',self.c[2]:'off'})
                self.assertEqual([model['short_labels'][c] for c in self.c],['1번 ON','1번','1번 OFF'])
                fills=wf.route_cable_signal_fills(model)
                self.assertEqual(fills[self.c[0]],wf.ROUTE_SIGNAL_FILLS['on']);self.assertEqual(fills[self.c[2]],wf.ROUTE_SIGNAL_FILLS['off'])
                self.assertEqual(self.snapshot(),before);self.s.close()

    def test_single_signal_route_has_plain_labels(self):
        s=self.open(True,('on','unknown','on'))
        model=wf.core_connection_highlight(s,[(self.c[0],1)])
        self.assertEqual([model['short_labels'][c] for c in self.c],['1번']*3)
        self.assertEqual(wf.route_cable_signal_fills(model),{})

    def test_mixed_core_list(self):
        s=self.open(False,('on','unknown','off'))
        found=wf.signal_mixed_cores(s);self.assertEqual([e['core_id'] for e in found],['REAL-1'])
        self.assertEqual(found[0]['text'],'신호 섞임: ON 1 · OFF 1')
        self.assertEqual(sorted(slot for slot,_ in found[0]['slots']),sorted((c,1) for c in self.c))
        # 미입력 is neutral: ON + 미입력 is not mixed; temporary 임시-7 (ON/미입력/OFF on the fixture) is gone.
        with s.action('fix'):s.conn.execute("UPDATE cores SET signal='on' WHERE cable_id=? AND core_index=1",(self.c[2],))
        self.assertEqual([e['core_id'] for e in wf.signal_mixed_cores(s)],[])

    def test_warning_before_signal_makes_path_mixed(self):
        s=self.open(True,('on','unknown','unknown'));before=self.snapshot()
        text=wf.signal_mix_warning(s,[(self.c[2],1)],'off')
        self.assertIn('신호 섞임',text);self.assertIn('ON',text);self.assertIn('/A/1번',text)
        self.assertEqual(wf.signal_mix_warning(s,[(self.c[2],1)],'on'),'')
        self.assertEqual(wf.signal_mix_warning(s,[(self.c[2],1)],'unknown'),'')
        # Changing every ON number together is not a mix.
        self.assertEqual(wf.signal_mix_warning(s,[(c,1) for c in self.c],'off'),'')
        self.assertEqual(self.snapshot(),before)
        # Plain drawings change one ID everywhere, so the same ID never warns.
        self.s.close();s=self.open(False,('on','unknown','unknown'))
        self.assertEqual(wf.signal_mix_warning(s,[(self.c[2],1)],'off'),'')

    def test_empty_number_keeps_off(self):
        for field in (True,False):
            with self.subTest(field=field):
                s=self.open(field);slot=(self.c[0],5)
                with s.action('splice empty'):
                    s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(self.n[1],*sorted(((self.c[0],5),(self.c[1],5))) [0],*sorted(((self.c[0],5),(self.c[1],5)))[1]))
                before=dict(s.core(*slot));splices=s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0]
                s.set_empty_core_signal(slot,'off');after=dict(s.core(*slot))
                self.assertEqual(after['signal'],'off');self.assertEqual(str(after['core_id'] or ''),'')
                self.assertEqual(s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0],splices)
                self.assertEqual(code['core_signal_tag'](after),'signal_off');self.assertEqual(code['core_row_signal_text'](after),'OFF')
                self.assertEqual(code['core_row_signal_text'](before),'')
                with self.assertRaises(ValueError):s.set_empty_core_signal((self.c[0],1),'off')
                s.undo();self.assertEqual(dict(s.core(*slot)),before);self.s.close()


def ui_check():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showerror') as error, \
         patch.object(code['messagebox'],'showwarning') as warn:
        home=Path(temp);s,n,c=fixture(home/'ui.sqlite3',True);real_path(s,c,('on','unknown','off'))
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            app.store.close();app.store=s
            for i,nid in enumerate(n):s.update_node_pos(nid,150+i*300,260)
            app.refresh();app.update()
            # 1) Mixed-core list: click a row and the drawing shows ON/OFF per cable.
            d=code['CoreCheckDialog'](app,s);d.kind.set('신호섞임');d.reload();app.update()
            keys=[k for k in d.row_meta.values()];assert ('REAL-1',None) in keys,keys
            iid=next(i for i,k in d.row_meta.items() if k[0]=='REAL-1');d.tree.selection_set(iid);app.update();d.show_route();app.update()
            texts={app.canvas.itemcget(i,'text') for i in app.canvas.find_withtag('core_path_number') if app.canvas.type(i)=='text'}
            assert {'1번 ON','1번 OFF'}<=texts,texts
            fills={app.canvas.itemcget(i,'fill') for i in app.canvas.find_withtag('core_path_number') if app.canvas.type(i)=='rectangle'}
            assert wf.ROUTE_SIGNAL_FILLS['on'] in fills and wf.ROUTE_SIGNAL_FILLS['off'] in fills,fills
            words=code['route_legend_text'](app);assert '신호 섞임' in words,words
            d.destroy();app.update()
            # 2) Warning before a cable-editor edit makes the path mixed; No keeps the old signal.
            with app.store.action('reset'):s.conn.execute("UPDATE cores SET signal='unknown' WHERE cable_id=? AND core_index=1",(c[2],))
            e=code['CableDialog'](app,s,c[2]);app.update()
            e.tree.selection_set('1');e.load_selected();e.edit_vars[2].set('OFF')
            with patch.object(code['messagebox'],'askyesno',return_value=False) as ask:e.apply_core();app.update()
            assert ask.called and s.core(c[2],1)['signal']=='unknown',(ask.call_args,s.core(c[2],1)['signal'])
            e.edit_vars[2].set('OFF')
            with patch.object(code['messagebox'],'askyesno',return_value=True):e.apply_core();app.update()
            assert s.core(c[2],1)['signal']=='off',(e.edit_vars[2].get(),dict(s.core(c[2],1)),error.call_args_list,e.info.get())
            # 3) Empty number: OFF stays and shows in the list.
            e.tree.selection_set('5');e.load_selected();e.edit_vars[2].set('OFF')
            with patch.object(code['messagebox'],'askyesno',return_value=True):e.apply_core();app.update()
            assert s.core(c[2],5)['signal']=='off' and not str(s.core(c[2],5)['core_id'] or '')
            assert e.tree.set('5','signal')=='OFF',e.tree.item('5')
            e.destroy();app.update()
            assert not errors and not error.called,(errors,error.call_args_list,warn.call_args_list)
        finally:app.on_close()
    print('PASS UI mixed-core list, per-cable ON/OFF labels, mix warning and empty-number OFF')


if __name__=='__main__':
    result=unittest.main(exit=False,verbosity=1).result
    if not result.wasSuccessful():
        for _,trace in result.failures+result.errors:print('::error::'+trace.encode('ascii','backslashreplace').decode().replace('\n','%0A'))
        sys.exit(1)
    try:ui_check()
    except BaseException:
        import traceback;print('::error::'+traceback.format_exc().encode('ascii','backslashreplace').decode().replace('\n','%0A'));sys.exit(1)
    print('PASS signal mix')
