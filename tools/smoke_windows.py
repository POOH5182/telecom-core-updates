"""Exercise real Windows/Tk initialization and the requested LOT editor before publishing."""
import json
import csv
import os
from pathlib import Path
import runpy
import sys
import tempfile
import traceback
import xml.etree.ElementTree as ET
from unittest.mock import patch

from telecom_updater import InstanceLock, UpdateError

ROOT = Path(__file__).resolve().parents[1]


def check_facility_headers(code, app):
    store = app.store
    rn = store.add_node('기존 RN', 400, 200, node_type='rn')
    store.ensure_ports(rn, {'mp': 2, 'sp': 1, 'p': 8})
    store.update_core('PORT:' + rn, 1, ('RN-TEST-CORE', '기존 포트', 'normal', '', 'on'))
    ports = [dict(r) for r in store.cores('PORT:' + rn)]
    extra = json.loads(store.node(rn)['extra_json'])
    before = dict(store.node(rn))
    editor = code['NodeDialog'](app, store, rn)
    editor.name_var.set('변경 RN명')
    editor.rn_id_var.set('RN-001')
    editor.rn_computer_var.set('00001234')
    groups = len(store.history_rows())
    editor.save_button.invoke()
    assert len(store.history_rows()) == groups + 1
    assert store.node(rn)['name'] == '변경 RN명'
    assert code['rn_details'](store.node(rn)) == ('RN-001', '00001234')
    assert [dict(r) for r in store.cores('PORT:' + rn)] == ports
    for key, value in extra.items():
        assert json.loads(store.node(rn)['extra_json'])[key] == value
    saved = dict(store.node(rn))
    store.undo()
    assert dict(store.node(rn)) == before
    store.redo()
    assert dict(store.node(rn)) == saved
    editor.destroy()
    properties = code['NodePropertiesDialog'](app, store, rn)
    assert (properties.rn_id.get(), properties.rn_computer.get()) == ('RN-001', '00001234')
    properties.name.set('최종 RN명')
    properties.rn_computer.set('00005678')
    properties.save()
    assert code['rn_details'](store.node(rn)) == ('RN-001', '00005678')
    assert [dict(r) for r in store.cores('PORT:' + rn)] == ports

    subscriber = store.add_node('기존 가입자', 600, 200, node_type='sub')
    ports = [dict(r) for r in store.cores('PORT:' + subscriber)]
    app.deiconify()
    app.focus_force()
    app.update()
    editor = code['open_detail_dialog'](app, store, 'node', subscriber)
    app.update()
    assert app.focus_get() is editor.name_entry, app.focus_get()
    assert editor.name_entry.selection_present()
    app.clipboard_clear()
    app.clipboard_append('포항 가입자 001')
    editor.name_entry.event_generate('<Control-v>')
    app.update()
    assert editor.name_entry.get() == '포항 가입자 001'
    assert store.node(subscriber)['name'] == '기존 가입자'
    editor.name_entry.event_generate('<space>')
    app.update()
    assert store.node(subscriber)['name'] == '포항 가입자 001'
    assert editor.name_entry.get() == '포항 가입자 001'
    assert '저장 완료' in editor.header_status.get()
    assert [dict(r) for r in store.cores('PORT:' + subscriber)] == ports
    # Space in a core table must keep its connection action, separate from
    # Space in the subscriber-name entry.
    with patch.object(editor, 'connect_auto') as connect:
        editor.left_tree.focus_force()
        app.update()
        editor.left_tree.event_generate('<space>')
        app.update()
        connect.assert_called_once()
    editor.destroy()
    app.focus_force()
    app.update()
    editor = code['open_detail_dialog'](app, store, 'node', subscriber)
    app.update()
    assert app.focus_get() is editor.name_entry
    assert editor.name_entry.selection_present()
    editor.destroy()
    print('PASS RN name/ID/computer number and ports, atomic header undo, subscriber initial focus, clipboard paste and Space save')
    return rn, subscriber


def check_bulk_keyboard(code, app):
    wf = code['App'].__init__.__globals__['workflow']
    store = app.store
    a = store.add_node('Space 시작', 800, 300)
    h = store.add_node('Space 함체', 1000, 300)
    b = store.add_node('Space 끝', 1200, 300)
    left = store.add_cable(a, h, 'SPACE-L', '12C', '기설')
    right = store.add_cable(h, b, 'SPACE-R', '12C', '기설')
    store.connect(h, (left, 1), (right, 1), temporary=True)
    node = code['NodeDialog'](app, store, h)
    sheet = code['BulkTableConnectDialog'](node, store, h)
    header = ['코어ID', '코어명', '회선번호', '회선명', '가입자명', '중요여부', 'SPACE-L', 'SPACE-R']
    row = ['SPACE-ID', 'Space 적용', '', '', '', '', '1', '1']
    sheet._grow_columns(8)
    sheet.data[0] = header
    sheet.data[1] = row
    sheet._configure_columns()
    sheet.reload_grid()
    failures = []
    mode = ['apply']
    original = wf.BulkSummaryDialog

    class KeyboardPreview(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.after(40, self.drive)

        def drive(self):
            try:
                expected = self.accept_button or self.cancel_button
                focused = self.focus_get()
                assert focused is not None and focused.winfo_toplevel() is self, focused
                if self.accept_button is not None:
                    assert focused is self.accept_button, focused
                expected.event_generate('<KeyRelease-space>')
                assert self.winfo_exists() and not self.accepted
                if mode[0] == 'cancel':
                    expected.event_generate('<Escape>')
                    return
                if mode[0] == 'blocked':
                    assert self.accept_button is None
                    assert str(self.title_label.cget('foreground')) == '#c62828'
                    iid = self.table.get_children()[0]
                    self.table.selection_set(iid)
                    assert self.table.item(iid, 'values')[0] == 'BAD-ID'
                    style = code['ttk'].Style(self)
                    assert style.lookup(self.table.cget('style'), 'foreground', ('selected',)) == '#c62828'
                # Verify Space also applies when keyboard focus is on Close.
                self.cancel_button.focus_force()
                self.update()
                self.cancel_button.event_generate('<KeyPress-space>')
                assert self.winfo_exists() and not self.accepted
                self.cancel_button.event_generate('<KeyRelease-space>')
            except Exception as error:
                failures.append(traceback.format_exc())
                if self.winfo_exists():self.destroy()

    with patch.object(wf, 'BulkSummaryDialog', KeyboardPreview):
        groups = len(store.history_rows())
        sheet.run()
        assert not failures, failures
        assert store.core(left, 1)['core_id'] == 'SPACE-ID'
        assert store.core(right, 1)['core_id'] == 'SPACE-ID'
        assert len(store.history_rows()) == groups + 1
        saved = wf.plan_snapshot(store.conn)
        mode[0] = 'blocked'
        sheet.data[2] = ['BAD-ID', '오류 행', '', '', '', '', '999', '2']
        sheet.run()
        assert not failures, failures
        assert wf.plan_snapshot(store.conn) == saved
        assert str(sheet.result_label.cget('foreground')) == '#c62828'
        assert sheet.output_tree.get_children()
        mode[0] = 'cancel'
        sheet.data[2] = [''] * 8
        sheet.data[1] = ['CANCEL-ID', '취소 검증', '', '', '', '', '2', '2']
        sheet.run()
        assert not failures, failures
        assert wf.plan_snapshot(store.conn) == saved
    sheet.destroy()
    node.destroy()
    print('PASS actual Excel inspection: popup focus, Space apply from Close, no accidental release apply, red selected errors, blocked no-write and Escape cancel')


def prepare_route_checks(code, store):
    a = store.add_node('경로 시작', 1400, 0)
    h = store.add_node('경로 함체', 1600, 0)
    b = store.add_node('경로 끝', 1800, 0)
    c = store.add_node('분리 시작', 2000, 400)
    d = store.add_node('분리 끝', 2200, 400)
    left = store.add_cable(a, h, 'CHECK-L', '12C', '기설')
    right = store.add_cable(h, b, 'CHECK-R', '6C', '기설')
    separate = store.add_cable(c, d, 'CHECK-SEPARATE', '6C', '기설')
    store.update_core(left, 3, ('CHECK-ID', '', 'normal', '', 'off'))
    store.connect(h, (left, 3), (right, 5))
    store.update_core(separate, 2, ('CHECK-ID', '', 'normal', '', 'off'))
    store.update_core(left, 4, ('CHECK-ID-OTHER', '', 'normal', '', 'off'))
    store.update_core(left, 5, ('', 'ID 없는 내역', '', '', ''))
    store.connect(h, (left, 6), (right, 6), temporary=True)
    temporary = store.core(left, 6)['core_id']
    store.conn.execute('INSERT INTO survey_rows VALUES(?,?,?,?,?,?,?,?,?)',
                       ('check-survey', h, left, 4, right, 5, 0, '', ''))
    store.conn.commit()
    rows = store.before_drawing_check_rows()
    assert any(r['category'] == '코어 경로' and r['core_id'] == 'CHECK-ID' for r in rows)
    assert any(r['category'] == '임시코어' and r['core_id'] == temporary for r in rows)
    missing = [r for r in rows if r['category'] == '코어 입력' and not r['core_id']]
    assert any(r['cable_id'] == left and r['core_index'] == 5 for r in missing)
    mismatches = [r for r in rows if '일괄입력 오류: 오류코어: 왼쪽' in r['message']]
    assert {r['core_id'] for r in mismatches} == {'CHECK-ID', 'CHECK-ID-OTHER'}
    assert all(r['core_id'] for r in rows if r['category'] in ('코어 연결', '코어 경로', '임시코어'))
    return {left: '3번', right: '5번', separate: '2번'}


def check_route_checks(code, app):
    expected = prepare_route_checks(code, app.store)
    app.refresh()
    wf = code['App'].__init__.__globals__['workflow']
    saved = wf.plan_snapshot(app.store.conn)

    def click(window, iid, column):
        window.tree.see(iid)
        app.update()
        x, y, width, height = window.tree.bbox(iid, column)
        window.tree.event_generate('<ButtonPress-1>', x=x + width // 2, y=y + height // 2)
        window.tree.event_generate('<ButtonRelease-1>', x=x + width // 2, y=y + height // 2)
        app.update()

    def check_highlight(window, view):
        assert app.highlight_owner is window
        assert app.highlight_core_labels == expected, app.highlight_core_labels
        assert app.highlight_cable_colors == {cid: '#ff7a00' for cid in expected}
        assert len(view['groups']) == 2, view
        texts = [window.diagram.itemcget(i, 'text') for i in window.diagram.find_all()
                 if window.diagram.type(i) == 'text']
        assert any('CHECK-L(3번 코어)' in text for text in texts), texts
        assert any('CHECK-R(5번 코어)' in text for text in texts), texts
        assert any('CHECK-SEPARATE(2번 코어)' in text for text in texts), texts

    window = code['ConnectionListDialog'](app, app.store, mode='incomplete')
    iid = str(next(i for i, r in enumerate(window.entries) if r['core_id'] == 'CHECK-ID'))
    click(window, iid, 'core')
    check_highlight(window, window._error_trace_view)
    window.destroy()
    app.update()
    assert not app.highlight_core_labels and not app.highlight_cables
    window = code['BeforeDrawingCheckDialog'](app, app.store)
    assert window.tree.heading('core_id', 'text') == '코어ID'
    ids = [r['core_id'] for r in window.rows if r['core_id']]
    assert len(ids) == len(set(ids)), ids
    iid = str(next(i for i, r in enumerate(window.visible) if r['core_id'] == 'CHECK-ID'))
    assert window.tree.item(iid, 'values')[3] == 'CHECK-ID'
    click(window, iid, 'core_id')
    check_highlight(window, window._trace_view)
    grouped = window.selected_row()
    members = [r for r in app.store.before_drawing_check_rows() if r['core_id'] == 'CHECK-ID']
    assert len(members) > 1 and list(grouped['_check_items']) == members
    assert all(r['message'] in window.issue_details.get('1.0', 'end') for r in members)
    # Reordering the grouped list still opens the selected diagnostic's cable.
    window.tree.cycle_sort('core_id'); window.tree.cycle_sort('core_id'); app.update()
    click(window, iid, 'core_id'); check_highlight(window, window._trace_view)
    destination = next(i for i, r in enumerate(members) if r['cable_id'] in expected and not r['category'].startswith('현장 '))
    window.issue_location.current(destination)
    opened = []
    namespace = type(window).__init__.__globals__
    with patch.dict(namespace, open_detail_dialog=lambda parent, store, kind, key: opened.append((kind, key))):
        window.open_selected()
    assert opened == [('cable', members[destination]['cable_id'])]
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'completion.csv'
        with patch.object(code['filedialog'], 'asksaveasfilename', return_value=str(path)), \
             patch.object(code['messagebox'], 'showinfo', return_value=None):
            window.csv_save()
        with path.open(encoding='utf-8-sig', newline='') as file:
            exported = list(csv.reader(file))[1:]
        matches = [r for r in exported if r[3] == 'CHECK-ID']
        assert len(matches) == 1 and all(r['message'] in matches[0][4] for r in members)
    window.tree.reset_sort(); app.update()
    missing = str(next(i for i, r in enumerate(window.visible)
                       if not r['core_id'] and r['category'] == '코어 입력'))
    click(window, missing, 'core_id')
    assert not app.highlight_cables and not window._trace_view
    assert '코어ID가 없습니다' in window.trace_summary.get()
    click(window, iid, 'core_id')
    window.filter.set('경고')
    window.show_rows()
    app.update()
    assert not app.highlight_cables and not window._trace_view
    assert not window.issue_location.get()
    assert all(r['level'] == '경고' for r in window.visible)
    assert len({r['core_id'] for r in window.visible if r['core_id']}) == sum(bool(r['core_id']) for r in window.visible)
    window.filter.set('전체'); window.reload(); app.update()
    assert len([r for r in window.rows if r['core_id'] == 'CHECK-ID']) == 1
    window.destroy()
    app.update()
    assert wf.plan_snapshot(app.store.conn) == saved
    print('PASS real incomplete/completeness row clicks: exact core IDs, split paths, cable/core labels, orange highlight and selection/filter/close cleanup; no drawing writes')
    print('PASS unique completeness core IDs, all reasons, selected issue location, sorted route selection and one-row-per-core CSV export')


def main():
    if sys.platform != 'win32':
        raise RuntimeError('This release gate must run on the Windows runner.')
    sys.path.insert(0, str(ROOT / 'app'))
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        os.environ['TELECOM_APP_HOME'] = str(home)
        code = runpy.run_path(str(ROOT / 'app' / 'telecom_core_app.pyw'), run_name='release_smoke')
        errors = []
        with patch.object(code['messagebox'], 'showerror', side_effect=lambda *a, **k: errors.append(str(a))):
            app = code['App']()
            app.withdraw()
            app.report_callback_exception = lambda *error: errors.append(str(error))
            a = app.store.add_node('검증 함체 A', 0, 0)
            b = app.store.add_node('검증 함체 B', 100, 0)
            dialog = code['CableDialog'](app, app.store, create_nodes=(a, b))
            dialog.id_var.set('CABLE-TEST')
            dialog.lot_var.set('00001 LOT-A')
            dialog.save_header()
            cable_id = dialog.cable_key
            assert code['cable_lot_no'](app.store.cable(cable_id)) == '00001 LOT-A'
            edit = code['CableDialog'](app, app.store, cable_id=cable_id)
            assert edit.lot_entry.get() == '00001 LOT-A'
            edit.lot_var.set('LOT-B 00002')
            edit.save_header()
            edit.destroy()
            app.update_idletasks()
            assert not errors, errors
            app.store.undo()
            assert code['cable_lot_no'](app.store.cable(cable_id)) == '00001 LOT-A'
            app.store.redo()
            assert code['cable_lot_no'](app.store.cable(cable_id)) == 'LOT-B 00002'
            # Exercise LOT editing and display through the real windows, then
            # check the same labels in the canvas and printable SVG.
            lot_edit = code['CableDialog'](app, app.store, cable_id=cable_id)
            lot_edit.size_var.set('144C')
            lot_edit.lot_var.set('123')
            lot_edit.save_header()
            lot_edit.destroy()
            # A prior release could store this field. Current enclosure edits
            # preserve it internally while exposing LOT only on cables.
            app.store.set_hamche_details(a, '', '', 'LEGACY-HAMCHE')
            node_edit = code['NodeDialog'](app, app.store, a)
            original_node = dict(app.store.node(a))
            groups = len(app.store.history_rows())
            node_edit.name_var.set('통합 저장 함체')
            node_edit.hamche_spec_var.set('12')
            node_edit.hamche_id_var.set('TEST-ID')
            assert 'hamche_lot_var' not in node_edit.__dict__
            node_edit.save_button.invoke()
            assert len(app.store.history_rows()) == groups + 1
            assert app.store.node(a)['name'] == '통합 저장 함체'
            assert node_edit.hamche_spec_var.get() == '12C'
            assert code['hamche_details'](app.store.node(a)) == ('12C', 'TEST-ID')
            node_edit.destroy()
            assert code['hamche_lot_no'](app.store.node(a)) == 'LEGACY-HAMCHE'
            app.store.undo()
            assert dict(app.store.node(a)) == original_node
            assert code['hamche_lot_no'](app.store.node(a)) == 'LEGACY-HAMCHE'
            app.store.redo()
            properties = code['NodePropertiesDialog'](app, app.store, a)
            assert 'hamche_lot' not in properties.__dict__
            properties.hamche_spec.set('144C')
            properties.save()
            assert code['hamche_details'](app.store.node(a))[0] == '144C'
            assert code['hamche_lot_no'](app.store.node(a)) == 'LEGACY-HAMCHE'
            app.store.undo()
            assert code['hamche_lot_no'](app.store.node(a)) == 'LEGACY-HAMCHE'
            app.store.redo()

            def display(cable_lot, cable_id_visible=False):
                settings = code['DisplaySettingsDialog'](app)
                assert 'hamche_lot' not in settings.values
                for key, value in dict(cable_lot=cable_lot,
                                       cable_id=cable_id_visible, hamche_spec=False,
                                       hamche_id=False).items():
                    settings.values[key].set(value)
                revision = app.store.data_revision()
                settings.apply()
                assert app.store.data_revision() == revision
                assert code['read_display_options'](app.display_options_path) == app.display_options
                canvas = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_all()
                          if app.canvas.type(i) == 'text']
                svg = ET.fromstring(app.drawing_svg())
                printed = [t.text for t in svg.findall('{http://www.w3.org/2000/svg}text')]
                assert not any('LEGACY-HAMCHE' in (text or '') for text in canvas + printed)
                return canvas, printed

            for labels in display(True):
                assert '144C =123=' in labels, labels
            for labels in display(False):
                assert '144C' in labels and '144C =123=' not in labels
            for labels in display(False, True):
                assert '144C(CABLE-TEST)' in labels
            for labels in display(True, True):
                assert '144C =123= (CABLE-TEST)' in labels
            assert code['hamche_detail_text'](app.store.node(b), app.display_options) == ''
            # Existing callers changing spec/ID must retain the new LOT value.
            app.store.set_hamche_details(a, 'NEW-SPEC', 'NEW-ID')
            assert code['hamche_lot_no'](app.store.node(a)) == 'LEGACY-HAMCHE'
            app.store.set_node_locked(a, True)
            try:
                app.store.set_hamche_details(a, 'NEW-SPEC', 'NEW-ID', 'SHOULD-NOT-SAVE')
            except ValueError:
                pass
            else:
                raise AssertionError('Locked enclosure LOT was editable')
            assert code['hamche_lot_no'](app.store.node(a)) == 'LEGACY-HAMCHE'
            app.store.set_node_locked(a, False)
            rn, subscriber = check_facility_headers(code, app)
            check_bulk_keyboard(code, app)
            check_route_checks(code, app)
            app.update_idletasks()
            assert not errors, errors
            path = app.store.path
            app.on_close()
        store = code['Store'](path)
        assert code['cable_lot_no'](store.cable(cable_id)) == '123'
        assert code['hamche_lot_no'](store.node(a)) == 'LEGACY-HAMCHE'
        assert store.node(rn)['name'] == '최종 RN명'
        assert code['rn_details'](store.node(rn)) == ('RN-001', '00005678')
        assert store.node(subscriber)['name'] == '포항 가입자 001'
        assert store.conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        store.close()
        with InstanceLock(home):
            try:
                with InstanceLock(home):
                    raise AssertionError('Second Windows launcher lock was permitted.')
            except UpdateError:
                pass
        with InstanceLock(home):
            pass
    print('PASS Windows Tk app, cable-only LOT display, facility headers, canvas/SVG, SQLite persistence, undo/redo, locks and instance lock')


if __name__ == '__main__':
    main()
