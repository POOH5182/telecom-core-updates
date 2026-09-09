"""Windows heading clicks must never change the record being edited or traced."""
import copy
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_field_survey import code, wf


class NaturalKeyTests(unittest.TestCase):
    def test_core_numbers_ids_sizes_and_rates(self):
        for values, expected in [
            (['10번', '2번', '1번'], ['1번', '2번', '10번']),
            (['CAB-10', 'CAB-2', 'CAB-1'], ['CAB-1', 'CAB-2', 'CAB-10']),
            (['144C', '12C', '36C'], ['12C', '36C', '144C']),
            (['9.5%', '9.12%', '100%'], ['9.12%', '9.5%', '100%']),
        ]:
            self.assertEqual(sorted(values, key=wf.table_natural_key), expected)


def windows_ui():
    if sys.platform != 'win32':
        return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME'] = temp
        errors = []
        with patch.object(code['messagebox'], 'showerror', side_effect=lambda *a, **k: errors.append(str(a))), \
             patch.object(code['messagebox'], 'showwarning', side_effect=lambda *a, **k: errors.append(str(a))), \
             patch.object(code['messagebox'], 'showinfo', return_value=None), \
             patch.object(code['messagebox'], 'askyesno', return_value=True), \
             patch.object(code['messagebox'], 'askyesnocancel', return_value=True):
            app = code['App']()
            app.report_callback_exception = lambda *args: errors.append(str(args))
            tick = 1000

            def click(tree, column):
                nonlocal tick
                app.update()
                first = tree.get_children()[0]
                box = tree.bbox(first, column)
                assert box, (column, tree.winfo_geometry())
                x = box[0] + min(box[2] // 2, 50)
                y = next(y for y in range(box[1]) if tree.identify_region(x, y) == 'heading')
                tick += 100  # Deliberately trigger Tk's double/triple-click paths.
                tree.event_generate('<ButtonPress-1>', x=x, y=y, time=tick)
                tree.event_generate('<ButtonRelease-1>', x=x, y=y, time=tick + 10)
                app.update()

            try:
                # Natural sort, equal keys, empty cells, rapid clicks, row IDs,
                # original order and active sort across reload/column replacement.
                dialog = wf.TableDialog(app, '정렬 검증', ('케이블ID', '코어번호'),
                                        [('C10', '10번'), ('C2', '2번'), ('C1', '1번'), ('', ''), ('C2', '2번')])
                tree = dialog.table
                app.update()
                original = tree.get_children()
                row_events = []
                tree.bind('<Double-Button-1>', lambda e: row_events.append('row action'))
                tree.selection_set(original[1]); tree.focus(original[1]); app.update()
                click(tree, 0)
                assert tree.get_children() == (original[2], original[1], original[4], original[0], original[3])
                assert tree.heading(0, 'text').endswith(' ▲')
                click(tree, 0)
                assert tree.get_children() == (original[0], original[1], original[4], original[2], original[3])
                assert tree.heading(0, 'text').endswith(' ▼')
                click(tree, 0)
                assert tree.get_children() == original and tree.heading(0, 'text') == '케이블ID'
                assert tree.selection() == (original[1],) and tree.focus() == original[1]
                assert not row_events
                click(tree, 1); click(tree, 0)
                assert tree.sort_direction == 1 and tree.heading(1, 'text') == '코어번호'
                tree.delete(*tree.get_children())
                second = [tree.insert('', 'end', values=v) for v in [('D10', 10), ('D2', 2)]]
                app.update(); assert tree.get_children() == tuple(reversed(second))
                tree.reset_sort(); assert tree.get_children() == tuple(second)
                tree.cycle_sort(0); tree.configure(columns=('new',)); tree.heading('new', text='새 열')
                assert tree.get_children() == tuple(second) and tree.sort_column is None
                dialog.destroy()

                s = app.store
                a=s.add_node('왼쪽 끝',100,300); h=s.add_node('정렬 함체',400,300); b=s.add_node('오른쪽 끝',700,300)
                left=s.add_cable(a,h,'A-10','12C','기설'); right=s.add_cable(h,b,'B-2','12C','기설')
                for index, identifier in ((1,'ID-10'),(2,'ID-2'),(10,'ID-1')):
                    s.update_core(left,index,(identifier,identifier+' 내역','normal','','off'))
                    s.connect(h,(left,index),(right,index))
                app.refresh(); app.update()
                snapshot = (wf.plan_snapshot(s.conn), s.data_revision(), s.history_rows())
                node = code['NodeDialog'](app,s,h)
                summary = code['NodeSummaryDialog'](node,s,h)
                app.update(); tree = summary.tree; original = tree.get_children()
                selected = next(i for i in original if summary.row_values[i]['core_id']=='ID-2')
                tree.selection_set(selected); app.update(); summary.vars[1].set('저장 전 메모')
                cables = [c for c in tree['columns'] if c.startswith('c')]
                column = next(c for c in cables if tree.heading_text(c).startswith('A-10'))
                click(tree,column)
                nonempty = [tree.set(i,column) for i in tree.get_children() if tree.set(i,column)]
                assert [int(v.split('번')[0]) for v in nonempty] == sorted(int(v.split('번')[0]) for v in nonempty)
                assert tree.selection()==(selected,) and summary.vars[1].get()=='저장 전 메모'
                summary.copy_table(); assert '▲' not in app.clipboard_get().splitlines()[0]
                click(tree,column); click(tree,column)
                assert tree.get_children()==original and summary.row_values[selected]['core_id']=='ID-2'
                assert (wf.plan_snapshot(s.conn),s.data_revision(),s.history_rows())==snapshot
                summary.destroy()

                cable = code['CableDialog'](app,s,left)
                cable.notebook.select(cable.identity_tab); app.update()
                tree = cable.identity_tree
                tree.selection_set('2'); cable.open_identity_editor('2','#3'); app.update()
                cable.identity_editor.delete(0,'end'); cable.identity_editor.insert(0,'선택 2번 수정')
                click(tree,'core_id')
                assert cable.identity_editor is None and tree.item('2','values')[2]=='선택 2번 수정'
                assert tree.get_children()[:3]==('10','2','1')
                assert s.core(left,2)['detail']=='ID-2 내역'
                # Inline edit and paste target physical row numbers even when
                # displayed in a different order; empty rows keep their offsets.
                tree.selection_set('1'); cable.identity_active_col='#2'
                app.clipboard_clear(); app.clipboard_append('\t첫째 수정\n\t\n\t셋째 수정')
                cable.paste_identity_from_clipboard(); app.update()
                assert tree.sort_column is None and tree.get_children()[0]=='1'
                assert tree.item('1','values')[2]=='첫째 수정' and tree.item('3','values')[2]=='셋째 수정'
                assert tree.item('2','values')[1:]==('ID-2','선택 2번 수정')
                cable.undo_identity_input(); app.update()
                assert tree.item('1','values')[2]=='ID-10 내역' and tree.item('3','values')[2]==''
                assert tree.item('2','values')[2]=='선택 2번 수정'
                # Save through the same reviewed batch flow, then undo the saved
                # change: both connected occurrences must still refer to core 2.
                original_init=wf.TableDialog.__init__
                def accept_review(self,*args,**kwargs):
                    original_init(self,*args,**kwargs)
                    if self._can_apply:self.after(30,self.confirm)
                with patch.object(wf.TableDialog,'__init__',accept_review):cable.apply_identity_changes()
                app.update()
                assert s.core(left,2)['detail']=='선택 2번 수정' and s.core(right,2)['detail']=='선택 2번 수정'
                assert s.core(left,1)['detail']=='ID-10 내역'
                s.undo(); app.refresh(); app.update()
                assert s.core(left,2)['detail']=='ID-2 내역'
                cable.destroy()

                # Completion trace previously used visible row positions. It
                # must locate the selected source record after reordering.
                targets=wf.CompletionTargetsDialog(app,s); app.update()
                targets.table.cycle_sort(1); app.update()
                iid=targets.table.get_children()[0]; expected=targets.entries[targets.row_indices[iid]]['core_id']
                targets.table.selection_set(iid); app.update()
                with patch.object(wf,'reveal_search_result') as reveal:
                    targets.locate(); assert reveal.call_args.args[1]['core_id']==expected
                targets.destroy()

                # Both Excel input tables pin their title row and retain source
                # row/column coordinates through edits, paste and undo.
                field=wf.FieldSurveyDialog(node,s,h); app.update()
                sheet=field.sheet; sheet.set_text('A-10\tB-2\n10\t10\n2\t2\n1\t1'); app.update()
                original_data=copy.deepcopy(sheet.data)
                click(sheet.tree,'c0'); assert sheet.tree.get_children()[:4]==('1','4','3','2')
                assert sheet.data==original_data
                sheet.focus_cell(2,1); sheet.begin_edit(); app.update()
                sheet.editor.delete(0,'end'); sheet.editor.insert(0,'8'); sheet.commit_editor(); app.update()
                assert sheet.data[2][1]=='8' and sheet.data[1][1]=='10'
                sheet.undo(); app.update(); assert sheet.data==original_data
                sheet.focus_cell(1,1); app.clipboard_clear(); app.clipboard_append('7\n6'); sheet.paste_excel(); app.update()
                assert sheet.tree.sort_column is None and sheet.data[1][1]=='7' and sheet.data[2][1]=='6'
                sheet.undo(); app.update(); assert sheet.data==original_data
                field.destroy()
                bulk=code['BulkTableConnectDialog'](node,s,h); app.update()
                app.clipboard_clear(); app.clipboard_append('A-10\tB-2\n10\t10\n2\t2\n1\t1')
                bulk.paste_from_a1(); app.update(); data=copy.deepcopy(bulk.data)
                click(bulk.tree,'c0'); assert bulk.tree.get_children()[:4]==('1','4','3','2')
                assert bulk.data==data
                bulk.active_cell=(1,1); app.clipboard_clear(); app.clipboard_append('7\n6'); bulk.paste_excel(); app.update()
                assert bulk.tree.sort_column is None and bulk.data[1][1]=='7' and bulk.data[2][1]=='6'
                bulk.destroy(); node.destroy()
                assert not errors, errors
            finally:
                app.on_close()
    print('PASS Windows three-way heading clicks, natural/default order, stable selection/edit/save/undo/trace, pinned Excel headers and paste offsets')


if __name__ == '__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NaturalKeyTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
