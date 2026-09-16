-- Maximum supported desktop payload, synthetic identity only; all rows roll back.
begin;
set local statement_timeout='60s';
do $$
declare
  actor uuid := gen_random_uuid();
  drawing uuid := gen_random_uuid();
  operation uuid := gen_random_uuid();
  bytes bytea;
  request jsonb;
  response jsonb;
  started timestamptz;
begin
  -- Deterministic high-entropy binary data, not customer drawings.
  select decode(string_agg(md5(i::text),''),'hex') into bytes from generate_series(1,524288) i;
  assert octet_length(bytes)=8388608;
  insert into auth.users(id,email,email_confirmed_at,raw_app_meta_data)
    values(actor,actor::text||'@example.invalid',now(),'{"provider":"google","providers":["google"]}');
  insert into auth.identities(user_id,provider_id,provider,identity_data)
    values(actor,actor::text,'google',jsonb_build_object('sub',actor::text));
  insert into telecom_private.members(user_id,email,status)
    values(actor,actor::text||'@example.invalid','approved');
  request:=jsonb_build_object('action','save','id',drawing,'operation_id',operation,
    'name','Synthetic maximum save','base_revision',0,'payload',encode(bytes,'base64'),
    'sha256',encode(sha256(bytes),'hex'));
  execute 'set local role authenticated';
  perform set_config('request.jwt.claims',jsonb_build_object('sub',actor)::text,true);
  started:=clock_timestamp();response:=public.telecom_call(request);
  assert clock_timestamp()-started<interval '8 seconds','Maximum save exceeds original eight-second budget';
  assert (response->>'revision')::int=1 and response->>'sha256'=request->>'sha256';
  assert not(response ? 'payload') and not(response ? 'owner_id') and not(response ? 'operation_id');
  assert octet_length(response::text)<1000,'Save acknowledgement contains drawing data';
  started:=clock_timestamp();response:=public.telecom_call(request);
  assert clock_timestamp()-started<interval '8 seconds','Maximum retry exceeds original eight-second budget';
  assert (response->>'revision')::int=1,'Retry duplicated revision';
  assert public.telecom_call(jsonb_build_object('action','load','id',drawing))->>'payload'=request->>'payload';
  execute 'reset role';
end;
$$;
rollback;
select 'PASS maximum 8 MiB save and idempotent retry each under 8 seconds; compact receipt and exact reload; synthetic rows rolled back' as result;
