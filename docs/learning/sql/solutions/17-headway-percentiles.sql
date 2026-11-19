-- PERCENTILE_CONT is an ordered-set aggregate: WITHIN GROUP gives the order.
-- It interpolates between values; PERCENTILE_DISC returns an actual value.
-- Postgres returns double precision here and has no ROUND(double, int):
-- write ROUND(CAST(PERCENTILE_CONT(...) ... AS NUMERIC), 1).
WITH operating AS (
    SELECT t.line_id,
           CAST(split_part(t.scheduled_start, ':', 1) AS INTEGER) * 60
         + CAST(split_part(t.scheduled_start, ':', 2) AS INTEGER) AS start_min
    FROM trips AS t
    JOIN trip_outcomes AS o ON o.trip_id = t.trip_id
    WHERE t.service_date = DATE '2026-11-04' AND t.direction_id = 0
      AND o.outcome IN ('ran', 'partial')
),
gaps AS (
    SELECT line_id,
           start_min - LAG(start_min) OVER (PARTITION BY line_id ORDER BY start_min) AS gap_min
    FROM operating
)
SELECT line_id,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY gap_min), 1) AS median_gap,
       ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY gap_min), 1) AS p90_gap
FROM gaps
WHERE gap_min IS NOT NULL
GROUP BY line_id;
