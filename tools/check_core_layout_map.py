"""Drawing-shaped whole-core map, reference sorting and live native Windows edits."""
import copy
import faulthandler
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_core_layout import code, wf, fixture


def pair_key(node, first, second):
    return node, tuple(sorted((tuple(first), tuple(second))))


def scene_pairs(scene):
    return {pair_key(group['node_id'], a, b)
            for group in scene['connections'] for a, b in group['pairs']}


def model_pairs(model):
    return {pair_key(panel['node']['id'], a, b)
            for panel in model['panels'] for group in panel['groups']
            for a, b in group['pairs']}


def insert_pair(store, node, first, second):
    a, b = sorted((first, second))
    store.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)', (node, *a, *b))


def extended_fixture(store):
    nodes, cables = fixture(store)
    detached = store.add_node('SYNTH 독립 말단', -260, 230, 'sub')
    branch = store.add_cable(nodes[1], detached, 'SYNTH-D', '12C', '신설')
    with store.action('후도면 선번 연결도 변경'):
        store.conn.execute("UPDATE nodes SET type='rn' WHERE id=?", (nodes[0],))
        store.conn.execute("INSERT INTO ports VALUES(?,1,'MP1','SYNTH-X','RN 내역','normal','','on')", (nodes[0],))
        insert_pair(store, nodes[0], ('PORT:' + nodes[0], 1), (cables[0], 3))
        for owner in cables[:2]:
            store.conn.execute("UPDATE cores SET core_id='SYNTH-X',detail='같은 ID 독립 구간' WHERE cable_id=? AND core_index=9", (owner,))
        insert_pair(store, nodes[1], (cables[0], 10), (cables[1], 11))
        store.conn.execute("UPDATE cores SET core_id='임시-987',detail='임시 내역',signal='on' WHERE cable_id=? AND core_index=12", (branch,))
    return nodes + [detached], cables + [branch]


class MapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = code['Store'](Path(self.temp.name) / 'drawing.sqlite3')
        self.nodes, self.cables = extended_fixture(self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def state(self):
        return wf.plan_snapshot(self.store.conn), wf.state(self.store), self.store.history_rows()

    def model(self):
        return wf.core_layout_model(wf.plan_snapshot(self.store.conn))

    def test_real_positions_every_pair_and_unconnected_used_numbers_are_visible(self):
        before = self.state()
        model = self.model()
        scene = wf.core_layout_map_scene(model)
        self.assertEqual(set(scene['anchors']), set(model['nodes']))
        # A common scale and translation retain the user's actual geometry
        # while making room for annotations; individual facilities cannot move.
        first = self.nodes[0]
        second = self.nodes[1]
        factor = ((scene['anchors'][second][0] - scene['anchors'][first][0]) /
                  (model['nodes'][second]['x'] - model['nodes'][first]['x']))
        self.assertGreater(factor, 0)
        offset = tuple(scene['anchors'][first][i] - factor * model['nodes'][first][axis]
                       for i, axis in enumerate(('x', 'y')))
        for nid, node in model['nodes'].items():
            for i, axis in enumerate(('x', 'y')):
                self.assertAlmostEqual(scene['anchors'][nid][i] - factor * node[axis], offset[i])
            self.assertTrue(any(shape.get('node_id') == nid for shape in scene['shapes']))
        for cable in self.cables:
            self.assertTrue(any(shape.get('cable_id') == cable and shape['kind'] == 'line'
                                for shape in scene['shapes']))
        self.assertEqual(scene_pairs(scene), model_pairs(model))
        represented = {cell['slot'] for cell in scene['cells']}
        for _, pair in model_pairs(model):
            self.assertTrue(set(pair) <= represented)
        self.assertTrue({(self.cables[0], 9), (self.cables[1], 9),
                         (self.cables[3], 12), ('PORT:' + self.nodes[0], 1)} <= represented)
        self.assertTrue(any(s.get('text') == 'MP1' for s in scene['shapes']))
        self.assertEqual(self.state(), before)

    def test_reference_sort_moves_connected_pairs_together_and_preserves_model(self):
        model = self.model()
        frozen = copy.deepcopy(model)
        before = self.state()
        for reference in self.cables[:3]:
            scenes = [wf.core_layout_map_scene(model, reference=reference, descending=direction)
                      for direction in (False, True)]
            self.assertEqual(scene_pairs(scenes[0]), scene_pairs(scenes[1]))
            self.assertEqual(scene_pairs(scenes[0]), model_pairs(model))
            for scene, descending in zip(scenes, (False, True)):
                for group in scene['connections']:
                    if reference not in group['owners']:
                        continue
                    numbers = [next(slot[1] for slot in pair if slot[0] == reference)
                               for pair in group['pairs']]
                    self.assertEqual(numbers, sorted(numbers, reverse=descending))
        # The crossed 3->7 / 4->3 pairs must not be independently sorted on
        # their two sides: the exact four physical path edges survive.
        self.assertIn(pair_key(self.nodes[1], (self.cables[0], 3), (self.cables[1], 7)),
                      scene_pairs(scenes[0]))
        self.assertEqual(model, frozen)
        self.assertEqual(self.state(), before)

    def test_reference_reaches_blank_transit_and_rn_but_not_same_id_gaps(self):
        model = self.model()
        index = wf.core_layout_reference_index(model, self.cables[1])
        self.assertEqual(index[(self.cables[0], 3)], (7,))
        self.assertEqual(index[(self.cables[2], 3)], (7,))
        self.assertEqual(index[('PORT:' + self.nodes[0], 1)], (7,))
        self.assertEqual(index[(self.cables[0], 10)], (11,))
        self.assertFalse(index.get((self.cables[0], 9)))
        self.assertFalse(index.get((self.cables[3], 12)))
        # A branching component can contain two reference numbers. Preserve
        # that ambiguity as both values, never choose a misleading single one.
        with self.store.action('후도면 선번 연결도 변경'):
            insert_pair(self.store, self.nodes[1], (self.cables[0], 3), (self.cables[3], 2))
            insert_pair(self.store, self.nodes[1], (self.cables[3], 2), (self.cables[1], 3))
        branched = self.model()
        index = wf.core_layout_reference_index(branched, self.cables[1])
        self.assertEqual(index[(self.cables[3], 2)], (3, 7))
        self.assertEqual(index[('PORT:' + self.nodes[0], 1)], (3, 7))
        scene = wf.core_layout_map_scene(branched, reference=self.cables[1])
        self.assertEqual(scene_pairs(scene), model_pairs(branched))

    def test_dense_crossed_pairs_are_never_truncated_or_rewritten(self):
        s = self.store
        for cable in self.cables[:2]:
            s.resize_cable(cable, '288C')
        with s.action('후도면 선번 연결도 변경'):
            s.conn.execute('DELETE FROM splices')
            for number in range(1, 289):
                insert_pair(s, self.nodes[1], (self.cables[0], number), (self.cables[1], 289 - number))
        before = self.state()
        model = self.model()
        scene = wf.core_layout_map_scene(model, reference=self.cables[1], descending=True)
        self.assertEqual(len(scene_pairs(scene)), 288)
        represented = {cell['slot'] for cell in scene['cells']}
        self.assertTrue(all((owner, number) in represented
                            for owner in self.cables[:2] for number in range(1, 289)))
        self.assertEqual(self.state(), before)

    def test_parallel_cable_curves_follow_live_row_order_without_mutating_data(self):
        parallel = self.store.add_cable(self.nodes[0], self.nodes[1], 'SYNTH-PARALLEL', '12C', '기설')
        before = self.state()
        model = self.model()
        # Deliberately oppose lexical key order, as a Store's insertion order
        # need not match the sorted snapshot keys used by the planning engine.
        order = sorted((parallel, self.cables[0]), reverse=True)
        model['cable_order'] = order + [owner for owner in model['cables'] if owner not in order]
        frozen = copy.deepcopy(model)
        first_scene = wf.core_layout_map_scene(model)

        def midpoint_offset(scene, owner):
            points = next(shape['points'] for shape in scene['shapes']
                          if shape.get('role') == 'cable' and shape.get('cable_id') == owner
                          and shape['kind'] == 'line')
            ax, ay = points[:2]
            bx, by = points[-2:]
            middle = (len(points) // 4) * 2
            mx, my = points[middle:middle + 2]
            length = ((bx - ax) ** 2 + (by - ay) ** 2) ** .5
            return ((bx - ax) * (my - (ay + by) / 2) -
                    (by - ay) * (mx - (ax + bx) / 2)) / length

        factor = first_scene['transform'][0]
        self.assertAlmostEqual(midpoint_offset(first_scene, order[0]), -17 * factor)
        self.assertAlmostEqual(midpoint_offset(first_scene, order[1]), 17 * factor)
        self.assertEqual(model, frozen)
        reversed_model = dict(model, cable_order=list(reversed(model['cable_order'])))
        second_scene = wf.core_layout_map_scene(reversed_model)
        self.assertAlmostEqual(midpoint_offset(second_scene, order[0]), 17 * factor)
        self.assertAlmostEqual(midpoint_offset(second_scene, order[1]), -17 * factor)
        self.assertEqual(scene_pairs(first_scene), scene_pairs(second_scene))
        self.assertEqual(self.state(), before)


def windows_ui():
    if sys.platform != 'win32':
        return
    faulthandler.dump_traceback_later(180, exit=True)
    with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'], 'showinfo'), patch.object(code['messagebox'], 'showwarning'), \
         patch.object(code['messagebox'], 'showerror') as error:
        app = code['App']()
        errors = []
        app.report_callback_exception = lambda *args: errors.append(args)
        try:
            s = app.store
            nodes, cables = extended_fixture(s)
            s.backup_to(app.scenario_path('before'))
            app.refresh()
            app.update()
            dialog = wf.open_core_layout(app)
            dialog.geometry('960x700+0+0')
            dialog.lift()
            app.update()
            dialog.initial_view()
            app.update()
            assert dialog.grab_current() is None
            assert wf.open_core_layout(app) is dialog
            assert dialog.display_mode.get() == '도면형'
            assert set(dialog.scene['anchors']) == set(nodes)
            assert scene_pairs(dialog.scene) == model_pairs(dialog.model)
            before = (wf.plan_snapshot(s.conn), wf.state(s), s.history_rows())

            print('MAP: real number click and reference cable ascending/descending controls', flush=True)
            slot = (cables[1], 7)
            dialog.focus_slot(slot)
            app.update()
            cell = next(cell for cell in dialog.scene['cells'] if cell['slot'] == slot)
            x = round((cell['x'] + cell.get('w', 24) / 2) * dialog.scale - dialog.canvas.canvasx(0))
            y = round((cell['y'] + cell.get('h', 24) / 2) * dialog.scale - dialog.canvas.canvasy(0))
            assert 0 <= x < dialog.canvas.winfo_width() and 0 <= y < dialog.canvas.winfo_height()
            dialog.canvas.event_generate('<ButtonPress-1>', x=x, y=y)
            dialog.canvas.event_generate('<ButtonRelease-1>', x=x, y=y)
            app.update()
            assert dialog.source == slot
            label = next(label for label, owner in dialog.sort_options.items() if owner == cables[1])
            dialog.sort_cable.set(label)
            dialog.sort_combo.event_generate('<<ComboboxSelected>>')
            app.update()
            assert dialog.sort_ref == cables[1]
            asc = copy.deepcopy(dialog.scene['connections'])
            dialog.sort_direction.set('내림차순')
            dialog.sort_direction_combo.event_generate('<<ComboboxSelected>>')
            app.update()
            desc = dialog.scene['connections']
            for a, b in zip(asc, desc):
                if cables[1] in a['owners']:
                    assert b['pairs'] == list(reversed(a['pairs'])), (a, b)
            assert (wf.plan_snapshot(s.conn), wf.state(s), s.history_rows()) == before
            dialog.display_mode.set('함체별 목록')
            dialog.display_mode_combo.event_generate('<<ComboboxSelected>>')
            app.update()
            assert dialog.scene.get('cards')
            dialog.display_mode.set('도면형')
            dialog.display_mode_combo.event_generate('<<ComboboxSelected>>')
            app.update()
            assert scene_pairs(dialog.scene) == model_pairs(dialog.model)

            print('MAP: external splice and facility move appear without refresh or losing input/view', flush=True)
            dialog.zoom_to(1.3)
            dialog.canvas.xview_moveto(.12)
            dialog.canvas.yview_moveto(.12)
            dialog.target.set('11')
            dialog.target_entry.focus_force()
            ready = wf.tk.BooleanVar()
            app.after(180, lambda: ready.set(True))
            app.wait_variable(ready)
            focus = app.focus_get()
            scale = dialog.scale
            def world_origin():
                factor, ox, oy = dialog.scene['transform']
                return ((dialog.canvas.canvasx(0) / dialog.scale - ox) / factor,
                        (dialog.canvas.canvasy(0) / dialog.scale - oy) / factor)
            viewport = world_origin()
            old_anchor = dialog.scene['anchors'][nodes[1]]
            old_geometry = tuple(float(s.node(nodes[1])[axis]) for axis in ('x', 'y'))
            with s.action('후도면 선번 연결도 변경'):
                first, second = sorted(((cables[0], 3), (cables[1], 7)))
                s.conn.execute('DELETE FROM splices WHERE node_id=? AND cable1_id=? AND core1_index=? AND cable2_id=? AND core2_index=?',
                               (nodes[1], *first, *second))
                insert_pair(s, nodes[1], (cables[0], 3), (cables[1], 6))
                s.conn.execute('UPDATE nodes SET x=x+41,y=y+29 WHERE id=?', (nodes[1],))
            # No App.refresh call: the modeless window must notice the commit.
            ready = wf.tk.BooleanVar()
            app.after(750, lambda: ready.set(True))
            app.wait_variable(ready)
            assert pair_key(nodes[1], (cables[0], 3), (cables[1], 6)) in scene_pairs(dialog.scene)
            assert pair_key(nodes[1], (cables[0], 3), (cables[1], 7)) not in scene_pairs(dialog.scene)
            assert tuple(dialog.model['nodes'][nodes[1]][axis] for axis in ('x', 'y')) == (old_geometry[0] + 41, old_geometry[1] + 29)
            assert dialog.scene['anchors'][nodes[1]] != old_anchor
            assert dialog.source == slot and dialog.target.get() == '11'
            assert dialog.sort_ref == cables[1] and dialog.sort_direction.get() == '내림차순'
            assert dialog.scale == scale and app.focus_get() is focus
            assert max(abs(a - b) for a, b in zip(viewport, world_origin())) < 2
            s.undo()
            app.refresh()
            app.update()

            print('MAP: projected exchange, apply and single undo retain both physical paths', flush=True)
            dialog.select_slot((cables[1], 7))
            dialog.target.set('3')
            dialog.review_button.invoke()
            app.update()
            assert dialog.preview and dialog.preview['kind'] == '교환'
            assert dialog.display_model()['slots'][cables[1], 3]['core_id'] == 'SYNTH-X'
            assert pair_key(nodes[1], (cables[0], 3), (cables[1], 3)) in scene_pairs(dialog.scene)
            assert wf.plan_snapshot(s.conn) == before[0]
            dialog.apply_button.invoke()
            app.update()
            assert s.core(cables[1], 3)['core_id'] == 'SYNTH-X'
            assert dialog.model['slots'][cables[1], 3]['core_id'] == 'SYNTH-X'
            assert pair_key(nodes[1], (cables[0], 4), (cables[1], 7)) in scene_pairs(dialog.scene)
            dialog.canvas.focus_force()
            dialog.canvas.event_generate('<Control-z>')
            app.update()
            assert wf.plan_snapshot(s.conn) == before[0]
            assert scene_pairs(dialog.scene) == model_pairs(dialog.model)
            dialog.sort_direction.set('오름차순')
            dialog.sort_direction_combo.event_generate('<<ComboboxSelected>>')
            dialog.select_slot((cables[1], 7))
            dialog.fit()
            app.update()
            for control in (dialog.display_mode_combo, dialog.sort_combo, dialog.sort_direction_combo):
                assert control.winfo_ismapped()
                assert control.winfo_rootx() + control.winfo_width() <= dialog.winfo_rootx() + dialog.winfo_width()
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True)
                screenshot(dialog, Path('dist') / 'v122-live-map.png')
            print('MAP: full drawing monitor view and restored edit controls', flush=True)
            editing_width = dialog.canvas.winfo_width()
            selected = dialog.source
            dialog.side_toggle_button.invoke()
            app.update()
            assert not dialog.side_visible and not dialog.side.winfo_ismapped()
            assert dialog.canvas.winfo_width() > editing_width
            assert dialog.source == selected
            dialog.fit()
            app.update()
            if '--emit-screenshots' in sys.argv:
                screenshot(dialog, Path('dist') / 'v122-live-map-full.png')
            dialog.side_toggle_button.invoke()
            app.update()
            assert dialog.side_visible and dialog.side.winfo_ismapped()
            for control in (dialog.tree, dialog.target_entry, dialog.review_button, dialog.apply_button):
                assert control.winfo_ismapped()
            assert dialog.source == selected
            dialog.destroy()
            app.update()
            assert dialog._watch is None and app._core_layout_window is None
            assert not errors, errors
            assert not error.called, error.call_args
        finally:
            app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows live drawing map, real click, reference sorting, external geometry/splices, focus/view preservation, preview/apply/undo and cleanup')


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MapTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    windows_ui()
