"""Display-only table sorting; physical slots and stable item IDs never change."""
import re
import unicodedata
from decimal import Decimal
import tkinter as tk
from tkinter import ttk


def table_natural_key(value):
    text = unicodedata.normalize('NFKC', str(value)).strip().casefold()
    # Numbered IDs, cable sizes and core cells (2번 before 10번).
    text = re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))', '', text)
    number = re.fullmatch(r'([+-]?\d+(?:\.\d+)?)\s*(%?)', text)
    if number:
        return ((0, Decimal(number[1])), (1, number[2]))
    return tuple((0, int(part)) if part.isdecimal() else (1, part)
                 for part in re.split(r'(\d+)', text) if part)


class SortableTreeview(ttk.Treeview):
    """Heading clicks cycle ascending, descending, then insertion order.

    Moves existing items only. Reloads establish their own default order while
    retaining the selected sort column. Empty cells stay last in either direction.
    Spreadsheet title rows can be pinned without changing their source row IDs.
    """
    def __init__(self, master=None, *, pinned_items=(), before_sort=None,
                 editor_active=None, **kwargs):
        self.sort_column = None
        self.sort_direction = 0
        self.before_sort = before_sort
        self.editor_active = editor_active
        self.pinned_items = set(map(str, pinned_items))
        self._sort_titles = {}
        self._sort_commands = {}
        self._default_order = {}
        self._sort_job = None
        self._sort_pressed = None
        super().__init__(master, **kwargs)
        # Handle rapid repeated heading clicks before row double-click bindings.
        # Separator gestures still reach Tk's normal resize handling.
        self._sort_tag = 'TableSort:' + str(self)
        self.bindtags((self._sort_tag,) + self.bindtags())
        for sequence in ('<ButtonPress-1>', '<Double-Button-1>', '<Triple-Button-1>'):
            self.bind_class(self._sort_tag, sequence, self._header_press)
        self.bind_class(self._sort_tag, '<ButtonRelease-1>', self._header_release)

    def _column_id(self, column):
        return '#0' if str(column) == '#0' else str(self.column(column, 'id'))

    def heading(self, column, option=None, **kwargs):
        if kwargs:
            key = self._column_id(column)
            if 'text' in kwargs:
                self._sort_titles[key] = str(kwargs['text'])
                kwargs['text'] = self._heading_label(key)
            if key not in self._sort_commands:
                self._sort_commands[key] = self._register(lambda c=key: self.cycle_sort(c))
            kwargs['command'] = self._sort_commands[key]
        return super().heading(column, option, **kwargs)

    def heading_text(self, column):
        """Undecorated title for clipboard/export (no sort arrows in cable IDs)."""
        key = self._column_id(column)
        return self._sort_titles.get(key, super().heading(column, 'text'))

    def _heading_label(self, key):
        suffix = (' ▲' if self.sort_direction == 1 else ' ▼') if key == self.sort_column else ''
        return self._sort_titles.get(key, '') + suffix

    def _render_headings(self):
        valid = {'#0', *map(str, self['columns'])}
        for key in list(self._sort_titles):
            if key in valid:
                super().heading(key, text=self._heading_label(key), command=self._sort_commands[key])
            else:
                del self._sort_titles[key]

    def configure(self, cnf=None, **kwargs):
        result = super().configure(cnf, **kwargs)
        options = dict(cnf) if isinstance(cnf, dict) else {}
        options.update(kwargs)
        if 'columns' in options:
            valid = {'#0', *map(str, self['columns'])}
            if self.sort_column is not None and self.sort_column not in valid:
                self.reset_sort(commit=False)
            self._render_headings()
        return result

    config = configure

    def _header_press(self, event):
        self._sort_pressed = None
        if self.identify_region(event.x, event.y) == 'heading':
            self._sort_pressed = self._column_id(self.identify_column(event.x))
            return 'break'

    def _header_release(self, event):
        column, self._sort_pressed = self._sort_pressed, None
        if column is not None:
            if (self.identify_region(event.x, event.y) == 'heading' and
                    self._column_id(self.identify_column(event.x)) == column):
                self.cycle_sort(column)
            return 'break'

    def cycle_sort(self, column):
        key = self._column_id(column)
        if self.before_sort:
            self.before_sort()
        direction = (self.sort_direction + 1) % 3 if self.sort_column == key else 1
        self.sort_column = key if direction else None
        self.sort_direction = direction
        self._cancel_sort_job()
        self._render_headings()
        self._apply_sort()
        self.yview_moveto(0)

    def reset_sort(self, commit=True):
        active = self.sort_column is not None
        if commit and self.before_sort:
            self.before_sort()
        self.sort_column = None
        self.sort_direction = 0
        self._cancel_sort_job()
        self._render_headings()
        self._apply_sort()
        return active

    def insert(self, parent, index, iid=None, **kwargs):
        item = super().insert(parent, index, iid, **kwargs)
        order = self._default_order.setdefault(str(parent), [])
        if str(index) == 'end':
            order.append(item)
        else:
            order.insert(max(0, int(index)), item)
        self._queue_sort()
        return item

    def delete(self, *items):
        removed = set()
        def collect(item):
            removed.add(str(item))
            for child in self.get_children(item):
                collect(child)
        for item in items:
            collect(item)
        result = super().delete(*items)
        for parent in list(self._default_order):
            if parent in removed:
                del self._default_order[parent]
            else:
                self._default_order[parent] = [i for i in self._default_order[parent] if i not in removed]
        self._queue_sort()
        return result

    def item(self, item, option=None, **kwargs):
        result = super().item(item, option, **kwargs)
        if 'values' in kwargs or 'text' in kwargs:
            self._queue_sort()
        return result

    def set(self, item, column=None, value=None):
        result = super().set(item, column, value)
        if value is not None:
            self._queue_sort()
        return result

    def _queue_sort(self):
        if self.sort_column is not None and self._sort_job is None:
            self._sort_job = self.after_idle(self._apply_sort)

    def _cancel_sort_job(self):
        if self._sort_job is not None:
            self.after_cancel(self._sort_job)
            self._sort_job = None

    def _apply_sort(self):
        self._sort_job = None
        # Background repaint must not commit or move an open cell editor.
        if self.editor_active and self.editor_active():
            return
        for parent, original in self._default_order.items():
            visible = set(self.get_children(parent))
            order = [i for i in original if i in visible]
            if self.sort_column is not None:
                pinned = [i for i in order if i in self.pinned_items]
                values = {i: str(self.item(i, 'text') if self.sort_column == '#0'
                                 else self.set(i, self.sort_column)).strip()
                          for i in order if i not in self.pinned_items}
                nonempty = [i for i in values if values[i]]
                nonempty.sort(key=lambda i: table_natural_key(values[i]), reverse=self.sort_direction == 2)
                order = pinned + nonempty + [i for i in values if not values[i]]
            for index, item in enumerate(order):
                super().move(item, parent, index)

    def destroy(self):
        self._cancel_sort_job()
        for sequence in ('<ButtonPress-1>', '<Double-Button-1>', '<Triple-Button-1>', '<ButtonRelease-1>'):
            self.unbind_class(self._sort_tag, sequence)
        super().destroy()
