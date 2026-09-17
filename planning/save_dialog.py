"""One modal confirmation, progress and acknowledged completion for drawing saves."""


class DrawingSaveDialog(RememberedToplevel):
    def __init__(self,parent,app):
        super().__init__(parent);self.app=app;self.store=app.store;self.editor_open=parent is not app
        self.generation=getattr(self.store,'_view_generation',0);self.kind=app.scenario_kind()
        self.cloud=getattr(app,'cloud',None);self.drawing_id=self.cloud.current if self.cloud else None
        self.save_phase='confirm';self.local_done=False;self.sync_timer=None;self.start_timer=None;self.focus_timer=None
        self._key_phases={};self._previous_grab=self.grab_current();self._closed=False
        self.title('저장');self.geometry('460x230');self.resizable(False,False)
        self.transient(parent);self.grab_set();self.protocol('WM_DELETE_WINDOW',self.close_notice)
        frame=ttk.Frame(self,padding=20);frame.pack(fill='both',expand=True)
        self.message=tk.StringVar(value='저장하시겠습니까?');self.detail=tk.StringVar()
        ttk.Label(frame,textvariable=self.message,font=('Malgun Gothic',12,'bold'),anchor='center',justify='center',wraplength=420).pack(fill='x',pady=(8,10))
        self.detail_label=ttk.Label(frame,textvariable=self.detail,anchor='center',justify='center',wraplength=420)
        self.detail_label.pack(fill='x')
        self.progress=ttk.Progressbar(frame,mode='indeterminate');self.progress.pack(fill='x',pady=12)
        self.progress.pack_forget()
        buttons=ttk.Frame(frame);buttons.pack(side='bottom',pady=(12,0))
        self.primary=ttk.Button(buttons,text='확인',command=self.primary_action,width=12);self.primary.pack(side='left',padx=4)
        self.secondary=ttk.Button(buttons,text='취소',command=self.close_notice,width=12);self.secondary.pack(side='left',padx=4)
        # Consume keys before TButton's class binding, so a repeat/release cannot
        # invoke both commands or dismiss the completed notice with the save key.
        self._key_tag='DrawingSaveKeys'+str(id(self));self._key_callbacks=[];pending=[self]
        while pending:
            widget=pending.pop();pending.extend(widget.winfo_children())
            widget.bindtags((self._key_tag,*widget.bindtags()))
        for key in ('space','Return'):
            self._key_callbacks.append(self.bind_class(self._key_tag,'<KeyPress-'+key+'>',self.key_press))
            self._key_callbacks.append(self.bind_class(self._key_tag,'<KeyRelease-'+key+'>',self.key_release))
        self._key_callbacks.append(self.bind_class(self._key_tag,'<Escape>',self.close_notice))
        self.focus_timer=self.after(50,self.focus_action)

    def focus_action(self):
        self.focus_timer=None
        if self.winfo_exists() and self.save_phase!='saving':self.primary.focus_force()

    def key_press(self,event):
        self._key_phases.setdefault(event.keysym,(self.save_phase,self.focus_get() is self.secondary))
        return 'break'

    def key_release(self,event):
        phase,secondary=self._key_phases.pop(event.keysym,(None,False))
        if phase==self.save_phase and phase!='saving':
            if secondary:self.close_notice()
            else:self.primary_action()
        return 'break'

    def primary_action(self):
        if self.save_phase=='complete':return self.close_notice()
        if self.save_phase not in ('confirm','error'):return 'break'
        self.save_phase='saving';self.title('저장 중');self.message.set('저장 중입니다…');self.detail.set('잠시만 기다려 주세요.')
        self.primary.configure(text='저장 중…',state='disabled');self.secondary.configure(state='disabled')
        self.progress.pack(fill='x',pady=12);self.progress.start(12)
        self.start_timer=self.after(25,self.save)
        return 'break'

    def save(self):
        self.start_timer=None
        try:
            if self.app.store is not self.store or getattr(self.store,'_view_generation',0)!=self.generation or self.app.scenario_kind()!=self.kind:
                raise ValueError('열린 도면이 변경되었습니다. 저장창을 닫고 다시 저장하세요.')
            if not self.local_done:
                self.app.save_current_snapshot();self.local_done=True
            if not self.cloud or not self.drawing_id:self.completed();return
            self.cloud.sync_now();self.refresh_sync()
        except Exception as error:self.failed(str(error))

    def refresh_sync(self):
        if self.sync_timer is not None:self.after_cancel(self.sync_timer)
        self.sync_timer=None
        if self._closed or not self.local_done or not self.cloud:return
        try:
            if self.app.store is not self.store or self.app.scenario_kind()!=self.kind:
                raise ValueError('열린 도면이 변경되어 저장 완료를 확인할 수 없습니다.')
            if self.cloud.current!=self.drawing_id:
                # Conflict preservation can create a new cloud ID for this exact
                # local file. Follow only that copy, never an unrelated drawing.
                if not self.cloud.current or self.cloud.working(self.cloud.entry()).resolve()!=self.store.path.resolve():
                    raise ValueError('저장 대상 도면이 변경되었습니다. 내 도면에서 저장 상태를 확인하세요.')
                self.drawing_id=self.cloud.current
            text=self.cloud.save_status(self.drawing_id)
            if text.startswith('클라우드 저장 완료'):self.completed();return
            if text.startswith('클라우드 저장 미완료'):
                self.failed(text)
            elif not self.cloud.jobs.busy and any((self.cloud.outbox()/(cid+'.json')).exists() for cid in getattr(self.cloud,'sync_errors',{})):
                self.failed('다른 도면의 클라우드 저장이 지연되고 있습니다. 다시 시도해 주세요.')
            else:
                if self.save_phase=='error':
                    self.save_phase='saving';self.title('저장 중');self.message.set('저장 중입니다…')
                    self.primary.configure(text='저장 중…',state='disabled');self.secondary.configure(state='disabled');self.progress.start(12)
                self.detail.set('PC 저장 완료 · 클라우드 저장 확인 중…')
                if not self.cloud.jobs.busy:self.cloud.sync_now()
            self.sync_timer=self.after(250,self.refresh_sync)
        except Exception as error:self.failed(str(error))

    def completed(self):
        self.save_phase='complete';self.title('저장 완료');self.message.set('저장 완료되었습니다.')
        self.detail.set('PC·클라우드 저장 완료' if self.cloud and self.drawing_id else '이 PC에 저장되었습니다.')
        if self.editor_open:self.detail.set(self.detail.get()+'\n편집창에 입력만 한 수정은 해당 창에서 적용해 주세요.')
        self.progress.stop();self.progress.pack_forget();self.secondary.pack_forget()
        self.primary.configure(text='확인',state='normal');self.primary.focus_force()
        self.app.status.set(self.detail.get())

    def failed(self,reason):
        self.save_phase='error';self.title('저장 확인');self.progress.stop();self.progress.pack_forget()
        self.message.set('클라우드 저장을 완료하지 못했습니다.' if self.local_done else '저장하지 못했습니다.')
        self.detail.set(('이 PC에는 저장되었습니다.\n' if self.local_done else '')+reason)
        self.primary.configure(text='다시 시도',state='normal');self.secondary.configure(text='닫기',state='normal')
        self.app.status.set(self.message.get()+' · '+reason)

    def close_notice(self,event=None):
        if self.save_phase!='saving':self.destroy()
        return 'break'

    def destroy(self):
        if self._closed:return
        self._closed=True
        for job in (self.start_timer,self.sync_timer,self.focus_timer):
            if job is not None:
                try:self.after_cancel(job)
                except tk.TclError:pass
        self.start_timer=self.sync_timer=self.focus_timer=None
        self.progress.stop()
        for key in ('space','Return'):
            self.unbind_class(self._key_tag,'<KeyPress-'+key+'>');self.unbind_class(self._key_tag,'<KeyRelease-'+key+'>')
        self.unbind_class(self._key_tag,'<Escape>')
        for callback in self._key_callbacks:self._root().deletecommand(callback)
        previous=self._previous_grab;super().destroy()
        try:
            if previous is not None and previous.winfo_exists():previous.grab_set()
        except tk.TclError:pass
