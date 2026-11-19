-- Reuse problem 08's latest-posting rule, then look for any ping at or after
-- the posting. A withdrawn cancellation is not a cancellation, so trip
-- 754-1-1103-0950, which pings after its withdrawn posting, is not an answer.
WITH latest AS (
    SELECT trip_id, posted_at, withdrawn_at,
           ROW_NUMBER() OVER (PARTITION BY trip_id ORDER BY posted_at DESC) AS rn
    FROM cancellations
)
SELECT l.trip_id, l.posted_at, MIN(v.observed_at) AS first_ping_after
FROM latest AS l
JOIN vehicle_positions AS v
  ON v.trip_id = l.trip_id AND v.observed_at >= l.posted_at
WHERE l.rn = 1 AND l.withdrawn_at IS NULL
GROUP BY l.trip_id, l.posted_at;
