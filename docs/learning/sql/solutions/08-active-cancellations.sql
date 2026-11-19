-- Pick the latest posting first, then drop withdrawn ones. Filtering
-- withdrawn rows first would bring back an older posting of a cancellation
-- that was called off, and count a trip that is running.
WITH latest AS (
    SELECT trip_id, service_date, withdrawn_at,
           ROW_NUMBER() OVER (PARTITION BY trip_id ORDER BY posted_at DESC) AS rn
    FROM cancellations
)
SELECT t.line_id, l.service_date, COUNT(*) AS active_cancellations
FROM latest AS l
JOIN trips AS t ON t.trip_id = l.trip_id
WHERE l.rn = 1 AND l.withdrawn_at IS NULL
GROUP BY t.line_id, l.service_date;
