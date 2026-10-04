-- ReasonTrace Phase 1. Synthetic personal-loan review only.
-- Run once in the dedicated Supabase demo project, then keep this file as the
-- reproducible source of truth. No applicant documents belong in public assets.

create table public.rt_cases (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  case_label text not null default 'RT-SYN-001',
  policy_version text not null default 'meridian-personal-loan-v1',
  synthetic boolean not null default true check (synthetic),
  status text not null default 'needs_review'
    check (status in ('needs_review', 'ready', 'auditing', 'audited')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, owner_id),
  unique (owner_id, case_label)
);

create table public.rt_documents (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references public.rt_cases(id) on delete cascade,
  kind text not null check (kind in ('pay_statement', 'bank_statement', 'credit_summary')),
  storage_path text not null unique,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  page_count integer not null default 1 check (page_count between 1 and 20),
  included boolean not null default true,
  reviewed boolean not null default false,
  created_at timestamptz not null default now(),
  unique (case_id, kind),
  unique (id, case_id)
);

create table public.rt_observations (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references public.rt_cases(id) on delete cascade,
  document_id uuid not null,
  field_key text not null check (field_key in
    ('applicant_name', 'annual_income_cents', 'monthly_debt_cents', 'credit_score',
     'statement_period', 'payroll_deposit')),
  raw_value text not null,
  parsed_value jsonb not null,
  source_quote text not null default '',
  page_number integer not null default 1 check (page_number between 1 and 20),
  extraction_mode text not null check (extraction_mode in ('fixture', 'interfaze')),
  confirmed_value jsonb,
  review_status text not null default 'unconfirmed'
    check (review_status in ('unconfirmed', 'confirmed', 'rejected')),
  extracted_at timestamptz not null default now(),
  reviewed_at timestamptz,
  foreign key (document_id, case_id) references public.rt_documents(id, case_id),
  unique (id, case_id)
);

create table public.rt_review_events (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references public.rt_cases(id) on delete cascade,
  observation_id uuid,
  actor_id uuid not null references auth.users(id),
  action text not null check (action in
    ('confirm', 'unconfirm', 'correct', 'reject', 'include_document', 'exclude_document', 'review_document')),
  before_value jsonb,
  after_value jsonb,
  created_at timestamptz not null default now(),
  foreign key (observation_id, case_id) references public.rt_observations(id, case_id)
);

create table public.rt_snapshots (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references public.rt_cases(id) on delete cascade,
  policy_version text not null,
  facts jsonb not null,
  provenance jsonb not null,
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  unique (id, case_id),
  unique (case_id, content_sha256)
);

create table public.rt_audit_runs (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references public.rt_cases(id) on delete cascade,
  snapshot_id uuid not null,
  agent_kind text not null check (agent_kind in ('faithful', 'laundering')),
  mode text not null default 'scripted_control' check (mode = 'scripted_control'),
  status text not null default 'running' check (status in ('running', 'completed', 'failed')),
  result jsonb,
  error_code text,
  created_at timestamptz not null default now(),
  finished_at timestamptz,
  foreign key (snapshot_id, case_id) references public.rt_snapshots(id, case_id),
  unique (snapshot_id, agent_kind)
);

create index rt_cases_owner_idx on public.rt_cases(owner_id, created_at desc);
create index rt_documents_case_idx on public.rt_documents(case_id);
create index rt_observations_case_idx on public.rt_observations(case_id, field_key);
create index rt_review_events_case_idx on public.rt_review_events(case_id, created_at desc);
create index rt_snapshots_case_idx on public.rt_snapshots(case_id, created_at desc);
create index rt_audit_runs_case_idx on public.rt_audit_runs(case_id, created_at desc);

alter table public.rt_cases enable row level security;
alter table public.rt_documents enable row level security;
alter table public.rt_observations enable row level security;
alter table public.rt_review_events enable row level security;
alter table public.rt_snapshots enable row level security;
alter table public.rt_audit_runs enable row level security;

revoke all on public.rt_cases, public.rt_documents, public.rt_observations,
  public.rt_review_events, public.rt_snapshots, public.rt_audit_runs from anon;
grant select, insert on public.rt_cases, public.rt_documents,
  public.rt_observations to authenticated;
grant update (case_label) on public.rt_cases to authenticated;
grant update (included, reviewed) on public.rt_documents to authenticated;
grant update (confirmed_value, review_status, reviewed_at)
  on public.rt_observations to authenticated;
grant select on public.rt_review_events to authenticated;
grant select on public.rt_snapshots, public.rt_audit_runs to authenticated;

create policy rt_cases_select on public.rt_cases for select to authenticated
  using (owner_id = (select auth.uid()));
create policy rt_cases_insert on public.rt_cases for insert to authenticated
  with check (owner_id = (select auth.uid()));
create policy rt_cases_update on public.rt_cases for update to authenticated
  using (owner_id = (select auth.uid()))
  with check (owner_id = (select auth.uid()));

create policy rt_documents_select on public.rt_documents for select to authenticated
  using (exists (select 1 from public.rt_cases c
    where c.id = case_id and c.owner_id = (select auth.uid())));
create policy rt_documents_insert on public.rt_documents for insert to authenticated
  with check (exists (select 1 from public.rt_cases c
    where c.id = case_id and c.owner_id = (select auth.uid())
      and storage_path like c.owner_id::text || '/' || c.id::text || '/%'));
create policy rt_documents_update on public.rt_documents for update to authenticated
  using (exists (select 1 from public.rt_cases c
    where c.id = case_id and c.owner_id = (select auth.uid())))
  with check (exists (select 1 from public.rt_cases c
    where c.id = case_id and c.owner_id = (select auth.uid())
      and storage_path like c.owner_id::text || '/' || c.id::text || '/%'));

create policy rt_observations_select on public.rt_observations for select to authenticated
  using (exists (select 1 from public.rt_cases c
    where c.id = case_id and c.owner_id = (select auth.uid())));
create policy rt_observations_insert on public.rt_observations for insert to authenticated
  with check (exists (select 1 from public.rt_cases c
    where c.id = case_id and c.owner_id = (select auth.uid())));
create policy rt_observations_update on public.rt_observations for update to authenticated
  using (exists (select 1 from public.rt_cases c
    where c.id = case_id and c.owner_id = (select auth.uid())))
  with check (exists (select 1 from public.rt_cases c
    where c.id = case_id and c.owner_id = (select auth.uid())));

create policy rt_review_events_select on public.rt_review_events for select to authenticated
  using (exists (select 1 from public.rt_cases c
    where c.id = case_id and c.owner_id = (select auth.uid())));
create policy rt_snapshots_select on public.rt_snapshots for select to authenticated
  using (exists (select 1 from public.rt_cases c
    where c.id = case_id and c.owner_id = (select auth.uid())));
create policy rt_audit_runs_select on public.rt_audit_runs for select to authenticated
  using (exists (select 1 from public.rt_cases c
    where c.id = case_id and c.owner_id = (select auth.uid())));

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('reasontrace-documents', 'reasontrace-documents', false, 10485760,
  array['image/png', 'image/jpeg', 'application/pdf'])
on conflict (id) do update set public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

create policy rt_storage_select on storage.objects for select to authenticated
  using (bucket_id = 'reasontrace-documents'
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and exists (select 1 from public.rt_cases c
      where c.id::text = (storage.foldername(name))[2]
        and c.owner_id = (select auth.uid())));
create policy rt_storage_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'reasontrace-documents'
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and exists (select 1 from public.rt_cases c
      where c.id::text = (storage.foldername(name))[2]
        and c.owner_id = (select auth.uid())));

-- Every reviewer edit creates a durable event, including direct Data API edits.
-- The client has SELECT but no INSERT/UPDATE/DELETE privileges on this ledger.
create function public.rt_log_observation_review() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
declare event_action text;
begin
  if old.confirmed_value is distinct from new.confirmed_value
     or old.review_status is distinct from new.review_status then
    if new.review_status = 'rejected' then event_action := 'reject';
    elsif new.review_status = 'unconfirmed' then event_action := 'unconfirm';
    elsif old.confirmed_value is distinct from new.confirmed_value
          and old.confirmed_value is not null then event_action := 'correct';
    else event_action := 'confirm';
    end if;
    insert into public.rt_review_events
      (case_id, observation_id, actor_id, action, before_value, after_value)
    values (new.case_id, new.id, (select auth.uid()), event_action,
      jsonb_build_object('confirmed_value', old.confirmed_value, 'status', old.review_status),
      jsonb_build_object('confirmed_value', new.confirmed_value, 'status', new.review_status));
  end if;
  return new;
end;
$$;
create trigger rt_observation_review_logged after update on public.rt_observations
for each row execute function public.rt_log_observation_review();

create function public.rt_log_document_review() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
declare event_action text;
begin
  if old.included is distinct from new.included
     or old.reviewed is distinct from new.reviewed then
    if old.included is distinct from new.included then
      event_action := case when new.included then 'include_document' else 'exclude_document' end;
    else event_action := 'review_document';
    end if;
    insert into public.rt_review_events
      (case_id, actor_id, action, before_value, after_value)
    values (new.case_id, (select auth.uid()), event_action,
      jsonb_build_object('document_id', new.id, 'included', old.included, 'reviewed', old.reviewed),
      jsonb_build_object('document_id', new.id, 'included', new.included, 'reviewed', new.reviewed));
  end if;
  return new;
end;
$$;
create trigger rt_document_review_logged after update on public.rt_documents
for each row execute function public.rt_log_document_review();
