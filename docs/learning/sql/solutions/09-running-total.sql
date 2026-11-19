-- Aggregate per day first, then window over the daily rows. A window
-- function runs after GROUP BY, so SUM(SUM(...)) OVER is legal too.
-- With ORDER BY and no frame, the default is RANGE BETWEEN UNBOUNDED
-- PRECEDING AND CURRENT ROW. RANGE includes every row tied on the ORDER BY
-- key; ROWS stops at the current row. Dates are unique here, so both agree.
WITH daily AS (
    SELECT t.service_date,
           SUM(CASE WHEN o.outcome = 'missed' THEN 1 ELSE 0 END) AS missed
    FROM trips AS t
    JOIN trip_outcomes AS o ON o.trip_id = t.trip_id
    WHERE t.line_id = '210'
    GROUP BY t.service_date
)
SELECT service_date, missed,
       SUM(missed) OVER (ORDER BY service_date
                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS missed_to_date
FROM daily
ORDER BY service_date;
