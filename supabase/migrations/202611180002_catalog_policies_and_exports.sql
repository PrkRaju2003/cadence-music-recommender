-- Public catalog reads need no privileged function. Private data remains RPC-only.
GRANT USAGE ON SCHEMA cadence TO anon,authenticated;
GRANT SELECT ON cadence.artists,cadence.genres,cadence.albums,cadence.tracks,cadence.track_catalog TO anon,authenticated;
CREATE POLICY read_catalog_artists ON cadence.artists FOR SELECT TO anon,authenticated USING(true);
CREATE POLICY read_catalog_genres ON cadence.genres FOR SELECT TO anon,authenticated USING(true);
CREATE POLICY read_catalog_albums ON cadence.albums FOR SELECT TO anon,authenticated USING(true);
CREATE POLICY read_catalog_tracks ON cadence.tracks FOR SELECT TO anon,authenticated USING(true);
CREATE POLICY own_genres ON cadence.user_genres FOR SELECT TO authenticated
USING(user_id IN (SELECT id FROM cadence.users WHERE auth_id=auth.uid()));
CREATE POLICY own_likes ON cadence.likes FOR SELECT TO authenticated
USING(user_id IN (SELECT id FROM cadence.users WHERE auth_id=auth.uid()));
CREATE POLICY own_requests ON cadence.recommendation_requests FOR SELECT TO authenticated
USING(user_id IN (SELECT id FROM cadence.users WHERE auth_id=auth.uid()));
CREATE POLICY own_recommendation_items ON cadence.recommendation_items FOR SELECT TO authenticated
USING(request_id IN (SELECT id FROM cadence.recommendation_requests WHERE user_id IN
                   (SELECT id FROM cadence.users WHERE auth_id=auth.uid())));
ALTER FUNCTION public.cadence_catalog() SECURITY INVOKER;
ALTER FUNCTION public.cadence_genres() SECURITY INVOKER;
ALTER FUNCTION public.cadence_health() SECURITY INVOKER;

CREATE FUNCTION public.cadence_export() RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,cadence AS $$
DECLARE uid bigint:=cadence.current_user_id(); result jsonb;
BEGIN
  result:=jsonb_build_object(
    'Playback',coalesce((SELECT jsonb_agg(to_jsonb(f) ORDER BY f.event_id) FROM cadence.playback_fact f WHERE user_id=uid),'[]'),
    'Tracks',coalesce((SELECT jsonb_agg(to_jsonb(t) ORDER BY t.track_id) FROM
      (SELECT id AS track_id,title,album_id,album,artist,genre,duration_ms FROM cadence.track_catalog) t),'[]'),
    'Users',jsonb_build_array(jsonb_build_object('user_id',uid,'listener','Listener '||uid::text)),
    'RecommendationRequests',coalesce((SELECT jsonb_agg(to_jsonb(r) ORDER BY r.requested_at) FROM
      (SELECT id AS request_id,user_id,requested_at,model_version,strategy,latency_ms
       FROM cadence.recommendation_requests WHERE user_id=uid) r),'[]'),
    'RecommendationItems',coalesce((SELECT jsonb_agg(to_jsonb(i)) FROM cadence.recommendation_items i
      JOIN cadence.recommendation_requests r ON r.id=i.request_id WHERE r.user_id=uid),'[]')
  );
  RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.cadence_export() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.cadence_export() TO authenticated;
NOTIFY pgrst,'reload schema';
