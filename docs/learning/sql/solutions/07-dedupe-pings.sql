-- ROW_NUMBER numbers the copies of each ping; keep copy 1, the earliest
-- received. DISTINCT can't do it because received_at differs between copies.
-- DuckDB shortcut: QUALIFY ROW_NUMBER() OVER (...) = 1, no subquery.
WITH numbered AS (
    SELECT vehicle_id, trip_id, observed_at, received_at,
           ROW_NUMBER() OVER (
               PARTITION BY vehicle_id, observed_at ORDER BY received_at
           ) AS copy
    FROM vehicle_positions
    WHERE trip_id LIKE '754-0-%'
)
SELECT vehicle_id, trip_id, observed_at, received_at
FROM numbered
WHERE copy = 1 AND observed_at < TIMESTAMP '2026-11-03 08:00:00';
