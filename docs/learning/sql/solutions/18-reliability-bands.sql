-- Same shape as fct_reliability: bucket, count, and hide rates on thin
-- cells. CASE with no ELSE returns NULL, which is the "not enough data"
-- answer, not 0.
WITH classified AS (
    SELECT t.line_id, o.outcome,
           CAST(split_part(t.scheduled_start, ':', 1) AS INTEGER) AS start_hour
    FROM trips AS t
    JOIN trip_outcomes AS o ON o.trip_id = t.trip_id
    WHERE t.service_date BETWEEN DATE '2026-11-02' AND DATE '2026-11-06'
),
banded AS (
    SELECT line_id, outcome,
           CASE WHEN start_hour < 6  THEN 'early'
                WHEN start_hour < 9  THEN 'am_peak'
                WHEN start_hour < 15 THEN 'midday'
                WHEN start_hour < 19 THEN 'pm_peak'
                WHEN start_hour < 24 THEN 'evening'
                ELSE 'owl' END AS band
    FROM classified
)
SELECT line_id, band, COUNT(*) AS trips,
       CASE WHEN COUNT(*) >= 30
            THEN ROUND(AVG(CASE WHEN outcome = 'ran' THEN 1.0 ELSE 0.0 END), 3)
       END AS ran_share
FROM banded
GROUP BY line_id, band;
