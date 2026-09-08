-- Account approval and optimistic, account-isolated drawing synchronization.
create schema if not exists telecom_private;
revoke all on schema telecom_private from public, anon;
grant usage on schema telecom_private to authenticated;

create table telecom_private.admin_emails (
  email text primary key check (email = lower(email))
);
create table telecom_private.members (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  role text not null default 'user' check (role in ('admin','user')),
  status text not null default 'pending' check (status in ('approved','pending','blocked')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table telecom_private.drawings (
  id uuid primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 120),
  revision bigint not null check (revision > 0),
  payload text not null check (octet_length(payload) <= 12000000),
  sha256 text not null,
  operation_id uuid not null,
  updated_at timestamptz not null default now()
);
create index drawings_owner_updated on telecom_private.drawings(owner_id, updated_at desc);
create table telecom_private.approval_audit (
  id bigint generated always as identity primary key,
  actor_id uuid not null,
  target_id uuid not null,
  status text not null,
  created_at timestamptz not null default now()
);
alter table telecom_private.admin_emails enable row level security;
alter table telecom_private.members enable row level security;
alter table telecom_private.drawings enable row level security;
alter table telecom_private.approval_audit enable row level security;
revoke all on all tables in schema telecom_private from public, anon, authenticated;

-- Privileged implementation is deliberately outside the exposed public schema.
-- Every action validates the authenticated Google identity and current membership.
create function telecom_private.dispatch(request jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  actor uuid := auth.uid();
  verified_email text;
  membership telecom_private.members%rowtype;
  item telecom_private.drawings%rowtype;
  action text := request->>'action';
  drawing_id uuid;
  operation uuid;
  target uuid;
  expected bigint;
  title text;
  payload text;
  digest text;
  result jsonb;
begin
  if actor is null then raise insufficient_privilege using message='LOGIN_REQUIRED'; end if;
  select lower(u.email) into verified_email from auth.users u
    where u.id=actor and u.email_confirmed_at is not null
      and u.deleted_at is null and not u.is_anonymous
      and (u.banned_until is null or u.banned_until <= now())
      and exists(select 1 from auth.identities i where i.user_id=u.id and i.provider='google');
  if verified_email is null then raise insufficient_privilege using message='GOOGLE_LOGIN_REQUIRED'; end if;
  if action='profile' then
    insert into telecom_private.members(user_id,email,role,status)
    values(actor,verified_email,
      case when exists(select 1 from telecom_private.admin_emails a where a.email=verified_email) then 'admin' else 'user' end,
      case when exists(select 1 from telecom_private.admin_emails a where a.email=verified_email) then 'approved' else 'pending' end)
    on conflict(user_id) do update set email=excluded.email;
  end if;
  select * into membership from telecom_private.members where user_id=actor;
  if membership.user_id is null then raise insufficient_privilege using message='APPROVAL_REQUIRED'; end if;
  if action='profile' then return to_jsonb(membership); end if;
  if membership.status <> 'approved' then raise insufficient_privilege using message='APPROVAL_REQUIRED'; end if;
  if action='users' then
    if membership.role <> 'admin' then raise insufficient_privilege using message='ADMIN_REQUIRED'; end if;
    select coalesce(jsonb_agg(to_jsonb(m) order by m.created_at desc),'[]'::jsonb)
      into result from telecom_private.members m;
    return result;
  elsif action='set_status' then
    if membership.role <> 'admin' then raise insufficient_privilege using message='ADMIN_REQUIRED'; end if;
    target := (request->>'user_id')::uuid;
    if request->>'status' is null or request->>'status' not in ('approved','blocked','pending') then raise exception 'INVALID_STATUS'; end if;
    update telecom_private.members set status=request->>'status', updated_at=now()
      where user_id=target and role='user';
    if not found then raise exception 'USER_NOT_FOUND_OR_ADMIN_PROTECTED'; end if;
    insert into telecom_private.approval_audit(actor_id,target_id,status) values(actor,target,request->>'status');
    return jsonb_build_object('ok',true);
  elsif action='list' then
    select coalesce(jsonb_agg(jsonb_build_object('id',d.id,'name',d.name,'revision',d.revision,
      'sha256',d.sha256,'updated_at',d.updated_at) order by d.updated_at desc),'[]'::jsonb)
      into result from telecom_private.drawings d where d.owner_id=actor;
    return result;
  elsif action='load' then
    select * into item from telecom_private.drawings where id=(request->>'id')::uuid and owner_id=actor;
    if item.id is null then raise no_data_found using message='DRAWING_NOT_FOUND'; end if;
    return to_jsonb(item)-'owner_id'-'operation_id';
  elsif action='save' then
    drawing_id := (request->>'id')::uuid;
    operation := (request->>'operation_id')::uuid;
    expected := (request->>'base_revision')::bigint;
    title := btrim(request->>'name');
    payload := request->>'payload';
    if drawing_id is null or operation is null or expected is null or expected < 0
      or title is null or char_length(title) not between 1 and 120
      or payload is null or octet_length(payload) not between 1 and 12000000 then
      raise exception 'INVALID_DRAWING';
    end if;
    digest := encode(sha256(decode(payload,'base64')),'hex');
    if request->>'sha256' is distinct from digest then raise exception 'CHECKSUM_MISMATCH'; end if;
    perform pg_advisory_xact_lock(hashtextextended(drawing_id::text,0));
    select * into item from telecom_private.drawings where id=drawing_id;
    if item.id is not null and item.owner_id <> actor then
      raise insufficient_privilege using message='DRAWING_NOT_FOUND';
    end if;
    if item.id is not null and item.operation_id=operation then
      if item.sha256 <> digest or item.name <> title then raise exception 'OPERATION_REUSED'; end if;
      return to_jsonb(item)-'payload'-'owner_id'-'operation_id';
    end if;
    if coalesce(item.revision,0) <> expected then
      raise serialization_failure using message='DRAWING_CONFLICT';
    end if;
    insert into telecom_private.drawings(id,owner_id,name,revision,payload,sha256,operation_id)
      values(drawing_id,actor,title,expected+1,payload,digest,operation)
    on conflict(id) do update set name=excluded.name,revision=excluded.revision,
      payload=excluded.payload,sha256=excluded.sha256,operation_id=excluded.operation_id,updated_at=now()
    returning * into item;
    return to_jsonb(item)-'payload'-'owner_id'-'operation_id';
  end if;
  raise exception 'UNKNOWN_ACTION';
end;
$$;
revoke all on function telecom_private.dispatch(jsonb) from public, anon, authenticated;
grant execute on function telecom_private.dispatch(jsonb) to authenticated;

create function public.telecom_call(request jsonb) returns jsonb
language sql security invoker set search_path = '' as $$
  select telecom_private.dispatch(request);
$$;
revoke all on function public.telecom_call(jsonb) from public, anon;
grant execute on function public.telecom_call(jsonb) to authenticated;
