-- Parse the GTFS time into seconds instead of comparing strings: lines 4
-- and 16 write '5:00:00', and '5:00:00' >= '24:00:00' is true as text.
-- Adding the seconds to the service date carries 25:10 into the next day.
-- (Postgres: service_date + make_interval(secs => ...).)
WITH parsed AS (
    SELECT trip_id, line_id, service_date,
           CAST(split_part(scheduled_start, ':', 1) AS INTEGER) * 3600
         + CAST(split_part(scheduled_start, ':', 2) AS INTEGER) * 60
         + CAST(split_part(scheduled_start, ':', 3) AS INTEGER) AS start_s
    FROM trips
    WHERE service_date = DATE '2026-11-02'
)
SELECT trip_id, line_id, service_date,
       CAST(service_date + to_seconds(start_s) AS DATE) AS departs_on,
       CAST(service_date + to_seconds(start_s) AS TIME) AS departs_at
FROM parsed
WHERE start_s >= 24 * 3600;
