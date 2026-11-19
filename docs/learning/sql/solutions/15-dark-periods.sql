-- Partition by trip, not vehicle: a vehicle runs many trips, and the time
-- between two of its trips is a layover, not the bus going dark.
-- Duplicates only add zero-second gaps, so they can't create a false dark
-- period here; dedupe anyway when the answer counts pings.
-- date_diff is DuckDB. Postgres: EXTRACT(EPOCH FROM observed_at - LAG(...)).
WITH gaps AS (
    SELECT trip_id,
           date_diff('second',
                     LAG(observed_at) OVER (PARTITION BY trip_id ORDER BY observed_at),
                     observed_at) AS gap_s
    FROM vehicle_positions
)
SELECT trip_id, COUNT(*) AS dark_gaps, MAX(gap_s) AS longest_gap_s
FROM gaps
WHERE gap_s > 120
GROUP BY trip_id;
