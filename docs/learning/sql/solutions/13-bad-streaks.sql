-- Islands on dates: subtract a row number (in days) from each bad date.
-- Consecutive dates land on the same anchor date; a skipped day moves it.
WITH daily AS (
    SELECT t.line_id, t.service_date,
           AVG(CASE WHEN o.outcome = 'missed' THEN 1.0 ELSE 0.0 END) AS share
    FROM trips AS t
    JOIN trip_outcomes AS o ON o.trip_id = t.trip_id
    GROUP BY t.line_id, t.service_date
),
bad AS (
    SELECT line_id, service_date,
           service_date - CAST(ROW_NUMBER() OVER (PARTITION BY line_id ORDER BY service_date) AS INTEGER) AS anchor
    FROM daily
    WHERE share > 0.10
),
streaks AS (
    SELECT line_id, MIN(service_date) AS streak_start, MAX(service_date) AS streak_end,
           COUNT(*) AS days
    FROM bad
    GROUP BY line_id, anchor
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY line_id ORDER BY days DESC, streak_start) AS rn
    FROM streaks
)
SELECT line_id, streak_start, streak_end, days
FROM ranked
WHERE rn = 1;
