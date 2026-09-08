-- Integration test: all synthetic users, memberships and drawings are rolled back.
begin;
do $$
declare
  administrator uuid := gen_random_uuid();
  person_a uuid := gen_random_uuid();
  person_b uuid := gen_random_uuid();
  unverified uuid := gen_random_uuid();
  drawing uuid := gen_random_uuid();
  operation uuid := gen_random_uuid();
  email_admin text := administrator::text || '@example.invalid';
  who uuid;
  response jsonb;
  request jsonb;
begin
  foreach who in array array[administrator,person_a,person_b,unverified] loop
    insert into auth.users(id,email,email_confirmed_at,raw_app_meta_data,raw_user_meta_data)
      values(who,who::text || '@example.invalid',now(),'{"provider":"google","providers":["google"]}',
        '{"role":"admin","status":"approved"}');
    if who <> unverified then
      insert into auth.identities(user_id,provider_id,provider,identity_data)
        values(who,who::text,'google',jsonb_build_object('sub',who::text));
    end if;
  end loop;
  insert into telecom_private.admin_emails(email) values(email_admin);
  execute 'set local role anon';
  begin
    perform public.telecom_call('{"action":"list"}');
    raise exception 'TEST: anonymous access allowed';
  exception when insufficient_privilege then null;
  end;
  execute 'reset role';
  execute 'set local role authenticated';
  perform set_config('request.jwt.claims',jsonb_build_object('sub',unverified)::text,true);
  begin
    perform public.telecom_call('{"action":"profile"}');
    raise exception 'TEST: non-Google identity allowed';
  exception when insufficient_privilege then null;
  end;
  foreach who in array array[administrator,person_a,person_b] loop
    perform set_config('request.jwt.claims',jsonb_build_object('sub',who)::text,true);
    response := public.telecom_call('{"action":"profile"}');
    if who=administrator then
      assert response->>'role'='admin' and response->>'status'='approved','Admin bootstrap failed';
    else
      assert response->>'role'='user' and response->>'status'='pending','User metadata escalated privileges';
      begin
        perform public.telecom_call('{"action":"list"}');
        raise exception 'TEST: pending user read allowed';
      exception when insufficient_privilege then null;
      end;
    end if;
  end loop;
  perform set_config('request.jwt.claims',jsonb_build_object('sub',administrator)::text,true);
  foreach who in array array[person_a,person_b] loop
    perform public.telecom_call(jsonb_build_object('action','set_status','user_id',who,'status','approved'));
  end loop;
  begin
    perform public.telecom_call(jsonb_build_object('action','set_status','user_id',administrator,'status','blocked'));
    raise exception 'TEST: admin blocked';
  exception when raise_exception then
    if sqlerrm <> 'USER_NOT_FOUND_OR_ADMIN_PROTECTED' then raise; end if;
  end;
  perform set_config('request.jwt.claims',jsonb_build_object('sub',person_a)::text,true);
  begin
    perform public.telecom_call('{"action":"users"}');
    raise exception 'TEST: ordinary user read approval list';
  exception when insufficient_privilege then null;
  end;
  begin
    perform public.telecom_call(jsonb_build_object('action','set_status','user_id',person_b,'status','blocked'));
    raise exception 'TEST: ordinary user approved another';
  exception when insufficient_privilege then null;
  end;
  begin
    perform count(*) from telecom_private.drawings;
    raise exception 'TEST: direct private table access allowed';
  exception when insufficient_privilege then null;
  end;
  request := jsonb_build_object('action','save','id',drawing,'operation_id',operation,
    'name','Synthetic integration drawing','base_revision',0,'payload','dGVzdA==',
    'sha256',encode(sha256(convert_to('test','UTF8')),'hex'));
  response := public.telecom_call(request);
  assert (response->>'revision')::int=1,'First save revision failed';
  response := public.telecom_call(request);
  assert (response->>'revision')::int=1,'Retry was not idempotent';
  response := public.telecom_call(request || jsonb_build_object('operation_id',gen_random_uuid(),'base_revision',1));
  assert (response->>'revision')::int=2,'Revision advancement failed';
  begin
    perform public.telecom_call(request || jsonb_build_object('operation_id',gen_random_uuid(),'base_revision',1));
    raise exception 'TEST: stale update replaced drawing';
  exception when serialization_failure then null;
  end;
  begin
    perform public.telecom_call(request || jsonb_build_object('sha256','wrong'));
    raise exception 'TEST: damaged payload accepted';
  exception when raise_exception then
    if sqlerrm <> 'CHECKSUM_MISMATCH' then raise; end if;
  end;
  perform set_config('request.jwt.claims',jsonb_build_object('sub',person_b)::text,true);
  assert public.telecom_call('{"action":"list"}')='[]'::jsonb,'Cross-account list leaked drawings';
  begin
    perform public.telecom_call(jsonb_build_object('action','load','id',drawing));
    raise exception 'TEST: cross-account download allowed';
  exception when no_data_found then null;
  end;
  begin
    perform public.telecom_call(request || jsonb_build_object('base_revision',2));
    raise exception 'TEST: cross-account write allowed';
  exception when insufficient_privilege then null;
  end;
  perform set_config('request.jwt.claims',jsonb_build_object('sub',administrator)::text,true);
  assert public.telecom_call('{"action":"list"}')='[]'::jsonb,'Admin could list another account drawings';
  perform public.telecom_call(jsonb_build_object('action','set_status','user_id',person_a,'status','blocked'));
  perform set_config('request.jwt.claims',jsonb_build_object('sub',person_a)::text,true);
  assert public.telecom_call('{"action":"profile"}')->>'status'='blocked','Profile reset approval';
  begin
    perform public.telecom_call('{"action":"list"}');
    raise exception 'TEST: blocked user still has access';
  exception when insufficient_privilege then null;
  end;
  execute 'reset role';
  update auth.users set banned_until=now()+interval '1 day' where id=person_b;
  execute 'set local role authenticated';
  perform set_config('request.jwt.claims',jsonb_build_object('sub',person_b)::text,true);
  begin
    perform public.telecom_call('{"action":"profile"}');
    raise exception 'TEST: banned Auth user allowed';
  exception when insufficient_privilege then null;
  end;
  execute 'reset role';
end;
$$;
rollback;
select 'PASS: anonymous, Google identity, approval, admin protection, owner isolation, checksum, retry, conflict, blocked and banned users; fixtures rolled back' as result;
