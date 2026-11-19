-- Filter to operating trips before LAG, so "previous" means the previous bus
-- that actually ran. Filtering after LAG would measure gaps to buses that
-- never came.
WITH operating AS (
    SELECT t.trip_id,
           CAST(split_part(t.scheduled_start, ':', 1) AS INTEGER) * 60
         + CAST(split_part(t.scheduled_start, ':', 2) AS INTEGER) AS start_min
    FROM trips AS t
    JOIN trip_outcomes AS o ON o.trip_id = t.trip_id
    WHERE t.line_id = '720' AND t.direction_id = 0
      AND t.service_date = DATE '2026-11-02'
      AND o.outcome IN ('ran', 'partial')
),
gaps AS (
    SELECT trip_id,
           LAG(trip_id)   OVER (ORDER BY start_min) AS prev_trip_id,
           start_min - LAG(start_min) OVER (ORDER BY start_min) AS gap_min
    FROM operating
)
SELECT trip_id, prev_trip_id, gap_min
FROM gaps
WHERE gap_min IS NOT NULL
ORDER BY gap_min DESC, trip_id
LIMIT 5;
