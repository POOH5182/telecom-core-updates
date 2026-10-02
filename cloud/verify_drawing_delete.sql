-- Synthetic rows only; never delete or alter a customer's drawing.
begin;
do $$
declare
  actor uuid := gen_random_uuid(); other_actor uuid := gen_random_uuid();
  pending_actor uuid := gen_random_uuid(); who uuid;
  drawing uuid := gen_random_uuid(); local_only uuid := gen_random_uuid();
  save_request jsonb; delete_request jsonb; response jsonb;
begin
  foreach who in array array[actor,other_actor,pending_actor] loop
    insert into auth.users(id,email,email_confirmed_at,raw_app_meta_data)
      values(who,who::text||'@example.invalid',now(),'{"provider":"google","providers":["google"]}');
    insert into auth.identities(user_id,provider_id,provider,identity_data)
      values(who,who::text,'google',jsonb_build_object('sub',who::text));
    insert into telecom_private.members(user_id,email,status)
      values(who,who::text||'@example.invalid',case when who=pending_actor then 'pending' else 'approved' end);
  end loop;
  save_request:=jsonb_build_object('action','save','id',drawing,'operation_id',gen_random_uuid(),
    'base_revision',0,'name','SYNTH deletion','payload',encode('synthetic payload'::bytea,'base64'),
    'sha256',encode(sha256('synthetic payload'::bytea),'hex'));
  delete_request:=jsonb_build_object('action','delete','id',drawing,'operation_id',gen_random_uuid(),
    'base_revision',1,'name','SYNTH deletion');
  execute 'set local role anon';
  begin
    perform public.telecom_call(delete_request);raise exception 'TEST anonymous delete allowed';
  exception when insufficient_privilege then null;end;
  execute 'reset role';execute 'set local role authenticated';
  perform set_config('request.jwt.claims',jsonb_build_object('sub',pending_actor)::text,true);
  begin
    perform public.telecom_call(delete_request);raise exception 'TEST unapproved delete allowed';
  exception when insufficient_privilege then null;end;
  perform set_config('request.jwt.claims',jsonb_build_object('sub',actor)::text,true);
  perform public.telecom_call(save_request);
  perform set_config('request.jwt.claims',jsonb_build_object('sub',other_actor)::text,true);
  begin
    perform public.telecom_call(delete_request);raise exception 'TEST cross-account delete allowed';
  exception when insufficient_privilege then null;end;
  perform set_config('request.jwt.claims',jsonb_build_object('sub',actor)::text,true);
  begin
    perform public.telecom_call(delete_request||'{"base_revision":0}');raise exception 'TEST stale delete allowed';
  exception when serialization_failure then null;end;
  response:=public.telecom_call(delete_request);
  assert response->>'deleted'='true' and response->>'revision'='2';
  assert public.telecom_call(delete_request)=response,'Delete retry changed revision';
  assert public.telecom_call('{"action":"list"}')='[]'::jsonb;
  assert public.telecom_call('{"action":"catalog"}')->'deleted'->0->>'id'=drawing::text;
  begin
    perform public.telecom_call(jsonb_build_object('action','load','id',drawing));raise exception 'TEST deleted load allowed';
  exception when sqlstate 'PT410' then null;end;
  begin
    perform public.telecom_call(save_request);raise exception 'TEST old save acknowledgement resurrected drawing';
  exception when sqlstate 'PT410' then null;end;
  begin
    perform public.telecom_call(save_request||jsonb_build_object('operation_id',gen_random_uuid(),'base_revision',0));
    raise exception 'TEST new save resurrected drawing';
  exception when sqlstate 'PT410' then null;end;
  perform set_config('request.jwt.claims',jsonb_build_object('sub',other_actor)::text,true);
  assert public.telecom_call('{"action":"catalog"}')->'deleted'='[]'::jsonb,'Other account saw deleted metadata';
  perform set_config('request.jwt.claims',jsonb_build_object('sub',actor)::text,true);
  response:=public.telecom_call(delete_request||jsonb_build_object('id',local_only,'base_revision',0));
  assert response->>'deleted'='true';
  begin
    perform public.telecom_call(save_request||jsonb_build_object('id',local_only));raise exception 'TEST offline pending save resurrected drawing';
  exception when sqlstate 'PT410' then null;end;
  execute 'reset role';
  assert (select payload from telecom_private.drawings where id=drawing)=save_request->>'payload','Deleted payload was lost';
end;
$$;
rollback;
select 'PASS owner-only CAS delete, approval/anonymous denial, idempotence, tombstones, old-client refusal and retained payload; synthetic data rolled back' as result;
