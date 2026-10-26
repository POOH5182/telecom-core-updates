"""Opening a ttk Combobox dropdown (e.g. cable editor signal) must not raise in the global Map handler."""
import os
import sys
import tkinter as tk
from tkinter import ttk
from check_after_plan import wf


def fail(message):
    print('::error::'+message);raise SystemExit(1)


def main():
    if sys.platform!='win32' and not os.environ.get('DISPLAY'):
        print('SKIP combobox dropdown: no display');return
    root=tk.Tk();errors=[]
    root.report_callback_exception=lambda kind,value,trace:errors.append(repr(value))
    try:
        wf.install_monitor_dialogs(root)
        page=tk.Toplevel(root);page.title('signal edit')
        signal=tk.StringVar()
        box=ttk.Combobox(page,textvariable=signal,values=('ON','OFF'),state='readonly');box.pack(padx=20,pady=20)
        root.update()
        root.tk.call('ttk::combobox::Post',box)
        for _ in range(20):root.update();root.after(20)
        popdown=root.tk.call('ttk::combobox::PopdownWindow',box)
        if not root.tk.call('winfo','ismapped',popdown):fail('combobox dropdown did not open')
        root.tk.call('ttk::combobox::Unpost',box);root.update()
        if errors:fail('combobox dropdown raised: '+' | '.join(errors))
        box.current(1);root.update()
        if signal.get()!='OFF':fail('combobox value not applied: '+repr(signal.get()))
        print('PASS combobox dropdown opens without Map handler errors')
    finally:
        root.destroy()


if __name__=='__main__':main()
