-- DENSE_RANK gives tied shares the same rank and leaves no gap after them,
-- so "top 3" can return more than three rows when there are ties.
-- RANK would leave a gap (1, 1, 3); ROW_NUMBER would break ties arbitrarily.
WITH daily AS (
    SELECT t.line_id, t.service_date,
           ROUND(AVG(CASE WHEN o.outcome = 'missed' THEN 1.0 ELSE 0.0 END), 3) AS missed_share
    FROM trips AS t
    JOIN trip_outcomes AS o ON o.trip_id = t.trip_id
    GROUP BY t.line_id, t.service_date
    HAVING COUNT(*) >= 40
),
ranked AS (
    SELECT *, DENSE_RANK() OVER (PARTITION BY service_date ORDER BY missed_share DESC) AS rnk
    FROM daily
)
SELECT service_date, line_id, missed_share, rnk
FROM ranked
WHERE rnk <= 3;
