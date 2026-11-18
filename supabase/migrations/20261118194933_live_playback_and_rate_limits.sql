-- Atomic fixed windows shared by every Vercel instance; no raw IP storage.
CREATE TABLE cadence.rate_windows (
  subject text NOT NULL, scope text NOT NULL, window_start bigint NOT NULL,
  hits integer NOT NULL CHECK(hits>0), touched_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(subject,scope)
);
CREATE INDEX rate_windows_expiry ON cadence.rate_windows(touched_at);
ALTER TABLE cadence.rate_windows ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON cadence.rate_windows FROM PUBLIC,anon,authenticated;
CREATE FUNCTION cadence.take_quota(p_subject text,p_scope text,p_limit integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,cadence AS $$
DECLARE w bigint:=floor(extract(epoch FROM clock_timestamp())/60); n integer;
BEGIN
  DELETE FROM cadence.rate_windows WHERE (subject,scope) IN
    (SELECT subject,scope FROM cadence.rate_windows WHERE touched_at<now()-interval '1 day' LIMIT 20);
  INSERT INTO cadence.rate_windows AS r VALUES(p_subject,p_scope,w,1,now())
  ON CONFLICT(subject,scope) DO UPDATE SET
    hits=CASE WHEN r.window_start=excluded.window_start THEN least(r.hits+1,p_limit+1) ELSE 1 END,
    window_start=excluded.window_start,touched_at=now() RETURNING hits INTO n;
  RETURN jsonb_build_object('allowed',n<=p_limit,'limit',p_limit,'remaining',greatest(0,p_limit-n),
    'retry_after',greatest(1,60-mod(floor(extract(epoch FROM clock_timestamp()))::bigint,60)));
END $$;
REVOKE ALL ON FUNCTION cadence.take_quota(text,text,integer) FROM PUBLIC,anon,authenticated;
CREATE FUNCTION public.cadence_rate_limit(p_subject text,p_scope text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,cadence AS $$
DECLARE quota integer;
BEGIN
  IF p_subject !~ '^[a-f0-9]{64}$' THEN RAISE EXCEPTION 'Invalid bucket' USING ERRCODE='22023'; END IF;
  quota:=CASE p_scope WHEN 'auth' THEN 10 WHEN 'recommendations' THEN 20 WHEN 'sql' THEN 30
    WHEN 'playback' THEN 120 WHEN 'media' THEN 180 WHEN 'api' THEN 120 END;
  IF quota IS NULL THEN RAISE EXCEPTION 'Invalid scope' USING ERRCODE='22023'; END IF;
  RETURN cadence.take_quota('ip:'||p_subject,p_scope,quota);
END $$;
REVOKE ALL ON FUNCTION public.cadence_rate_limit(text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cadence_rate_limit(text,text) TO anon,authenticated;
-- Account quotas also apply to direct authenticated RPC calls, not just our API.
CREATE FUNCTION cadence.limit_account_writes() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,cadence AS $$
DECLARE quota integer; result jsonb;
BEGIN
  IF auth.uid() IS NOT NULL THEN
    quota:=CASE TG_TABLE_NAME WHEN 'playback_events' THEN 120 WHEN 'listening_sessions' THEN 30
      WHEN 'recommendation_requests' THEN 20 ELSE 60 END;
    result:=cadence.take_quota('account:'||auth.uid()::text,TG_TABLE_NAME,quota);
    IF NOT (result->>'allowed')::boolean THEN
      RAISE sqlstate 'PGRST' USING message='{"code":"RATE_LIMIT","message":"Too many requests"}',
        detail=jsonb_build_object('status',429,'headers',jsonb_build_object('Retry-After',result->>'retry_after'))::text;
    END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cadence.limit_account_writes() FROM PUBLIC,anon,authenticated;
CREATE TRIGGER account_play_quota AFTER INSERT OR UPDATE ON cadence.playback_events FOR EACH ROW EXECUTE FUNCTION cadence.limit_account_writes();
CREATE TRIGGER account_session_quota AFTER INSERT ON cadence.listening_sessions FOR EACH ROW EXECUTE FUNCTION cadence.limit_account_writes();
CREATE TRIGGER account_rec_quota AFTER INSERT ON cadence.recommendation_requests FOR EACH ROW EXECUTE FUNCTION cadence.limit_account_writes();
CREATE TRIGGER account_like_quota AFTER INSERT ON cadence.likes FOR EACH ROW EXECUTE FUNCTION cadence.limit_account_writes();
-- Cumulative progress: one row per listening occurrence, retry/out-of-order safe.
CREATE FUNCTION public.cadence_play_progress(p_session_id text,p_track_id bigint,p_played_ms integer,p_source text,p_event_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,cadence AS $$
DECLARE uid bigint:=cadence.current_user_id(); result bigint;
BEGIN
  IF NOT EXISTS(SELECT 1 FROM cadence.listening_sessions WHERE id=p_session_id AND user_id=uid) THEN
    RAISE EXCEPTION 'Session not found' USING ERRCODE='42501'; END IF;
  IF p_source NOT IN ('catalog','recommendation') OR length(p_event_key) NOT BETWEEN 1 AND 100 THEN
    RAISE EXCEPTION 'Invalid event' USING ERRCODE='22023'; END IF;
  INSERT INTO cadence.playback_events AS e(session_id,track_id,played_ms,source,event_key)
  VALUES(p_session_id,p_track_id,p_played_ms,p_source,p_event_key)
  ON CONFLICT(event_key) DO UPDATE SET played_ms=greatest(e.played_ms,excluded.played_ms)
  WHERE e.session_id=excluded.session_id AND e.track_id=excluded.track_id AND e.source=excluded.source
  RETURNING id INTO result;
  IF result IS NULL THEN RAISE EXCEPTION 'Event key already used' USING ERRCODE='23505'; END IF;
  RETURN jsonb_build_object('id',result,'stored',true);
END $$;
REVOKE ALL ON FUNCTION public.cadence_play_progress(text,bigint,integer,text,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.cadence_play_progress(text,bigint,integer,text,text) TO authenticated;
