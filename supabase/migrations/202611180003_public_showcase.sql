-- Recruiter demo: these functions expose synthetic listeners/events only.
-- Real account data cannot enter any of these public report paths.
CREATE FUNCTION public.cadence_demo_users() RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,cadence AS $$ SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'display_name',display_name) ORDER BY id),'[]') FROM cadence.users WHERE is_demo $$;
CREATE FUNCTION public.cadence_demo_events() RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,cadence AS $$ SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.played_at,x.id),'[]') FROM
(SELECT e.id,e.session_id,s.user_id,e.track_id,e.played_at,1.0*e.played_ms/t.duration_ms AS completion
 FROM cadence.playback_events e JOIN cadence.listening_sessions s ON s.id=e.session_id
 JOIN cadence.users u ON u.id=s.user_id JOIN cadence.tracks t ON t.id=e.track_id WHERE u.is_demo AND e.source='seed') x $$;
CREATE FUNCTION public.cadence_demo_report(p_report text,p_user_id bigint DEFAULT 1,p_limit integer DEFAULT 20)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,cadence AS $$
DECLARE result jsonb;
BEGIN
  IF p_limit NOT BETWEEN 1 AND 50 OR NOT EXISTS(SELECT 1 FROM cadence.users WHERE id=p_user_id AND is_demo) THEN
    RAISE EXCEPTION 'Invalid demo listener or limit' USING ERRCODE='22023';
  END IF;
  IF p_report='top_tracks' THEN
    SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') INTO result FROM
    (SELECT c.title,c.artist,count(*) AS plays,round(avg(f.completion)*100,1) AS completion_pct
     FROM cadence.playback_fact f JOIN cadence.track_catalog c ON c.id=f.track_id WHERE f.user_id=p_user_id AND f.source='seed'
     GROUP BY c.id,c.title,c.artist ORDER BY plays DESC,c.title LIMIT p_limit) x;
  ELSIF p_report='daily_activity' THEN
    SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') INTO result FROM
    (SELECT play_date,count(*) AS plays,round(sum(played_ms)/60000.0,2) AS minutes FROM cadence.playback_fact
     WHERE user_id=p_user_id AND source='seed' GROUP BY play_date ORDER BY play_date DESC LIMIT p_limit) x;
  ELSIF p_report='catalog_summary' THEN
    SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') INTO result FROM
    (SELECT genre,count(*) AS tracks,count(DISTINCT album_id) AS albums FROM cadence.track_catalog GROUP BY genre ORDER BY genre LIMIT p_limit) x;
  ELSE RAISE EXCEPTION 'Unknown report' USING ERRCODE='22023'; END IF;
  RETURN result;
END $$;
CREATE FUNCTION public.cadence_demo_analytics() RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,cadence AS $$
DECLARE totals jsonb; daily jsonb; genres jsonb;
BEGIN
  SELECT jsonb_build_object('plays',count(*),'listeners',count(DISTINCT f.user_id),'sessions',count(DISTINCT session_id),
    'listening_minutes',round(sum(played_ms)/60000.0,2),'completion_pct',round(avg(completion)*100,1),'skip_pct',round(avg(skipped)*100,1))
  INTO totals FROM cadence.playback_fact f JOIN cadence.users u ON u.id=f.user_id WHERE u.is_demo AND f.source='seed';
  SELECT coalesce(jsonb_agg(to_jsonb(d) ORDER BY d.play_date),'[]') INTO daily FROM
    (SELECT play_date,count(*) AS plays,count(DISTINCT f.user_id) AS active_users FROM cadence.playback_fact f JOIN cadence.users u ON u.id=f.user_id
     WHERE u.is_demo AND f.source='seed' GROUP BY play_date) d;
  SELECT coalesce(jsonb_agg(to_jsonb(g) ORDER BY g.plays DESC),'[]') INTO genres FROM
    (SELECT c.genre,count(*) AS plays FROM cadence.playback_fact f JOIN cadence.track_catalog c ON c.id=f.track_id JOIN cadence.users u ON u.id=f.user_id
     WHERE u.is_demo AND f.source='seed' GROUP BY c.genre) g;
  RETURN jsonb_build_object('totals',totals,'daily',daily,'genres',genres,'model',jsonb_build_object('requests',0,'avg_latency_ms',null),
    'data_note','Fixed synthetic showcase data. Guest playback is not stored.');
END $$;
DO $$ DECLARE f record; BEGIN
  FOR f IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname='public' AND p.proname LIKE 'cadence_demo_%' LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated',f.signature);
    EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO anon,authenticated',f.signature);
  END LOOP;
END $$;
NOTIFY pgrst,'reload schema';
