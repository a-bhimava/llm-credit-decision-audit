-- Phase 3 hardening. Apply after SUPABASE_SECRET_KEY is configured on the server.
-- A signed-in browser may review its own sources, but may not invent documents
-- or model observations through the Data API. Server routes first verify the
-- reviewer with the session-scoped client, then perform these narrow inserts.
revoke insert on public.rt_documents, public.rt_observations from authenticated;

-- A direct Data API edit still receives an append-only review event. Use an
-- empty search path for these SECURITY DEFINER trigger functions.
alter function public.rt_log_observation_review() set search_path = '';
alter function public.rt_log_document_review() set search_path = '';
