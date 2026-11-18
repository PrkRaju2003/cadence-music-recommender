-- Rolls back every temporary account, progress event and quota bucket.
BEGIN;
DO $$
DECLARE a uuid:=gen_random_uuid(); b uuid:=gen_random_uuid(); sid text; key text:=gen_random_uuid()::text; q jsonb; denied boolean:=false;
BEGIN
  INSERT INTO auth.users(id,email,raw_user_meta_data) VALUES(a,a::text||'@example.test','{}'),(b,b::text||'@example.test','{}');
  PERFORM set_config('request.jwt.claim.sub',a::text,true);
  sid:=public.cadence_start_session()->>'id';
  PERFORM public.cadence_play_progress(sid,1,2000,'catalog',key);
  PERFORM public.cadence_play_progress(sid,1,6000,'catalog',key);
  PERFORM public.cadence_play_progress(sid,1,3000,'catalog',key);
  PERFORM public.cadence_play_progress(sid,1,6000,'catalog',key);
  IF (public.cadence_analytics()->'totals'->>'plays')::integer<>1 THEN RAISE EXCEPTION 'Progress inflated play count'; END IF;
  IF (public.cadence_history()->0->>'played_ms')::integer<>6000 THEN RAISE EXCEPTION 'Progress regressed'; END IF;
  PERFORM set_config('request.jwt.claim.sub',b::text,true);
  BEGIN PERFORM public.cadence_play_progress(sid,1,7000,'catalog',key);
  EXCEPTION WHEN insufficient_privilege THEN denied:=true; END;
  IF NOT denied THEN RAISE EXCEPTION 'Cross account progress accepted'; END IF;
  FOR i IN 1..10 LOOP q:=public.cadence_rate_limit(repeat('a',64),'auth'); END LOOP;
  IF NOT (q->>'allowed')::boolean THEN RAISE EXCEPTION 'Quota denied early'; END IF;
  q:=public.cadence_rate_limit(repeat('a',64),'auth');
  IF (q->>'allowed')::boolean THEN RAISE EXCEPTION 'Quota not enforced'; END IF;
  UPDATE cadence.rate_windows SET window_start=window_start-1 WHERE subject='ip:'||repeat('a',64);
  q:=public.cadence_rate_limit(repeat('a',64),'auth');
  IF NOT (q->>'allowed')::boolean OR (q->>'remaining')::integer<>9 THEN RAISE EXCEPTION 'Window did not reset'; END IF;
  IF has_table_privilege('anon','cadence.rate_windows','SELECT') OR has_function_privilege('anon','public.cadence_play_progress(text,bigint,integer,text,text)','EXECUTE') THEN RAISE EXCEPTION 'Private grants exposed'; END IF;
END $$;
SELECT 'monotonic progress, one play, ownership, quota rejection/reset and grants passed' AS verification;
ROLLBACK;
