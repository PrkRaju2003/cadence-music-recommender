-- Live integration check. Every test account and event is rolled back.
BEGIN;
DO $$
DECLARE a uuid:=gen_random_uuid(); b uuid:=gen_random_uuid(); bs text; aid bigint; rows jsonb; denied boolean:=false;
BEGIN
  INSERT INTO auth.users(id,email,raw_user_meta_data)
    VALUES(a,'sql-a-'||a::text||'@example.test','{"display_name":"SQL test A"}'::jsonb),
          (b,'sql-b-'||b::text||'@example.test','{"display_name":"SQL test B"}'::jsonb);
  PERFORM set_config('request.jwt.claim.sub',b::text,true);
  bs := public.cadence_start_session()->>'id';
  PERFORM public.cadence_record_play(bs,1,10000,'catalog','sql-test-'||b::text);
  PERFORM set_config('request.jwt.claim.sub',a::text,true);
  aid := (public.cadence_profile()->>'id')::bigint;
  IF jsonb_array_length(public.cadence_history())<>0 THEN RAISE EXCEPTION 'History leaked'; END IF;
  IF jsonb_array_length(public.cadence_training_events())<>4480 THEN RAISE EXCEPTION 'Training data leaked another account'; END IF;
  IF jsonb_array_length(public.cadence_demo_events())<>4480 THEN RAISE EXCEPTION 'Public demo leaked a real event'; END IF;
  IF jsonb_array_length(public.cadence_demo_users())<>40 THEN RAISE EXCEPTION 'Public demo leaked real profiles'; END IF;
  IF jsonb_array_length(public.cadence_export()->'Users')<>1 THEN RAISE EXCEPTION 'Export leaked profiles'; END IF;
  IF (public.cadence_analytics()->'totals'->>'plays')::integer<>0 THEN RAISE EXCEPTION 'Analytics leaked'; END IF;
  BEGIN
    PERFORM public.cadence_record_play(bs,1,1000,'catalog','sql-test-attack');
  EXCEPTION WHEN insufficient_privilege THEN denied:=true;
  END;
  IF NOT denied THEN RAISE EXCEPTION 'Cross-account playback accepted'; END IF;
  IF jsonb_array_length(public.cadence_sql_report('catalog_summary'))<>4 THEN RAISE EXCEPTION 'Catalog report failed'; END IF;
  IF has_function_privilege('anon','public.cadence_training_events()','EXECUTE') THEN RAISE EXCEPTION 'Anonymous training access'; END IF;
  IF NOT has_function_privilege('anon','public.cadence_catalog()','EXECUTE') THEN RAISE EXCEPTION 'Public catalog access missing'; END IF;
END $$;
SELECT 'account isolation, private analytics, SQL reports, and anonymous grants passed' AS verification;
ROLLBACK;
