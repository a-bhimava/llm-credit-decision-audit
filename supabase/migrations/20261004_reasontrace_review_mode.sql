-- Phase 2: keep fixture and live extractions distinct and idempotent.
alter table public.rt_cases add column active_extraction_mode text not null default 'fixture'
  check (active_extraction_mode in ('fixture', 'interfaze'));
grant update (active_extraction_mode) on public.rt_cases to authenticated;
create unique index rt_observations_doc_field_mode_idx
  on public.rt_observations(document_id, field_key, extraction_mode);
