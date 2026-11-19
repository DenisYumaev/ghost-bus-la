-- LAG must see every day before the filter: put it in a CTE and filter in
-- the outer query, because WHERE runs before window functions.
WITH daily AS (
    SELECT t.line_id, t.service_date,
           AVG(CASE WHEN o.outcome = 'missed' THEN 1.0 ELSE 0.0 END) AS share
    FROM trips AS t
    JOIN trip_outcomes AS o ON o.trip_id = t.trip_id
    GROUP BY t.line_id, t.service_date
),
paired AS (
    SELECT line_id, service_date, share,
           LAG(share) OVER (PARTITION BY line_id ORDER BY service_date) AS prev_share
    FROM daily
)
SELECT line_id, service_date,
       ROUND(prev_share, 3) AS prev_share,
       ROUND(share, 3) AS share,
       ROUND(share - prev_share, 3) AS change
FROM paired
WHERE share - prev_share > 0.05;
