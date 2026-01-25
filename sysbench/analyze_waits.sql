SELECT 
    left(s.query, 80) AS query,
    s.calls,
    round(s.total_exec_time::numeric, 4) AS total_ms,
    round((s.total_exec_time / s.calls)::numeric, 4) AS avg_ms,
    
    -- CPU stats from pg_stat_kcache
    round((k.exec_user_time + k.exec_system_time)::numeric, 3) AS cpu_sec,
    round(
        (100.0 * (k.exec_user_time + k.exec_system_time) / NULLIF(s.total_exec_time / 1000, 0))::numeric,
        1
    ) AS cpu_pct,
    
    -- I/O stats from pg_stat_kcache
    pg_size_pretty(k.exec_reads) AS disk_read,
    pg_size_pretty(k.exec_writes) AS disk_write,
    k.exec_reads_blks AS read_blks,
    k.exec_writes_blks AS write_blks,
    
    -- Wait events from pg_wait_sampling
    w.top_wait_event,
    w.top_wait_type,
    w.wait_samples,
    w.wait_events
    
FROM pg_stat_statements s
LEFT JOIN pg_stat_kcache_detail k ON k.query = s.query
LEFT JOIN LATERAL (
    SELECT 
        (array_agg(event ORDER BY count DESC))[1] AS top_wait_event,
        (array_agg(event_type ORDER BY count DESC))[1] AS top_wait_type,
        sum(count) AS wait_samples,
        count(DISTINCT event) AS wait_events
    FROM pg_wait_sampling_profile p
    WHERE p.queryid = s.queryid
      AND event IS NOT NULL
) w ON true
WHERE s.calls > 0
  AND s.total_exec_time > 0
ORDER BY s.total_exec_time DESC
LIMIT 200;