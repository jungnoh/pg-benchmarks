SELECT
    coalesce(event_type, 'CPU') AS event_type,
    coalesce(event, '-') AS event,
    sum(count) AS total_count,
    round(100.0 * sum(count) / NULLIF(sum(sum(count)) OVER (), 0), 2) AS pct_of_total
FROM pg_wait_sampling_profile
WHERE count > 0
GROUP BY event_type, event
ORDER BY total_count DESC;
