-- Distinguish an edited value from simply removing confirmation.
create or replace function public.rt_log_observation_review() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
declare event_action text;
begin
  if old.confirmed_value is distinct from new.confirmed_value
     or old.review_status is distinct from new.review_status then
    if new.review_status = 'rejected' then event_action := 'reject';
    elsif old.confirmed_value is distinct from new.confirmed_value
          and new.review_status = 'unconfirmed' then event_action := 'correct';
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
