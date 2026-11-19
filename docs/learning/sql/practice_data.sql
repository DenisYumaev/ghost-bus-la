-- Synthetic practice data shaped like the Ghost Bus LA warehouse.
--
-- Every number in these tables is invented (CLAUDE.md hard rule 11). The line
-- numbers are real LA Metro lines; the trips, outcomes, pings and outages are
-- not. Nothing here may be quoted as a finding about Metro.
--
-- The build is deterministic: no random(), only arithmetic on the row's own
-- values, so every run gives the same rows and the reference answers never move.
-- Timestamps are LA wall-clock time without a zone, so the drills stay about SQL.
--
-- Planted traps (the drills point at them):
--   * line 901 has no trips, and one line_stops row with a NULL stop_id
--   * lines 4 and 16 write GTFS times without the leading zero ('5:00:00')
--   * trips start as late as 25:30:00 (GTFS times past midnight)
--   * trips on 2026-11-08 from 22:00 on have no row in trip_outcomes yet
--   * some cancellations are posted twice; some latest postings are withdrawn
--   * some vehicle pings arrive twice (same observed_at, later received_at)
--   * some trips go dark for four minutes; a few canceled trips still ping

CREATE TEMP TABLE _plan AS SELECT * FROM (VALUES
    ('2',   15, 2,  4, 5),
    ('4',   20, 1,  3, 4),
    ('16',  30, 2,  6, 6),
    ('33',  30, 2,  5, 5),
    ('210', 40, 3, 11, 6),
    ('720', 12, 1,  3, 3),
    ('754', 15, 1,  2, 3)
) p(line_id, headway_min, cancel_pct, miss_pct, partial_pct);

CREATE TABLE lines AS SELECT * FROM (VALUES
    ('2',   'Line 2',   'local'),
    ('4',   'Line 4',   'local'),
    ('16',  'Line 16',  'local'),
    ('33',  'Line 33',  'local'),
    ('210', 'Line 210', 'local'),
    ('720', 'Line 720', 'rapid'),
    ('754', 'Line 754', 'rapid'),
    ('901', 'Line 901', 'brt')
) l(line_id, line_name, mode);

CREATE TABLE stops AS SELECT * FROM (VALUES
    ('S01', 'Vermont / Sunset'),
    ('S02', 'Vermont / Wilshire'),
    ('S03', 'Vermont / Santa Monica'),
    ('S04', 'Western / Wilshire'),
    ('S05', 'Western / Olympic'),
    ('S06', 'Sunset / Alvarado'),
    ('S07', 'Sunset / Western'),
    ('S08', 'Venice / Crenshaw'),
    ('S09', 'Venice / La Brea'),
    ('S10', 'Crenshaw / Adams'),
    ('S11', 'Wilshire / La Brea'),
    ('S12', 'Wilshire / Fairfax'),
    ('S13', 'Olympic / Fairfax'),
    ('S14', 'Beverly / Vermont')
) s(stop_id, stop_name);

CREATE TABLE line_stops AS SELECT * FROM (VALUES
    ('2',   'S06', 1), ('2',   'S07', 2), ('2',   'S01', 3),
    ('4',   'S03', 1), ('4',   'S07', 2),
    ('16',  'S04', 1), ('16',  'S11', 2), ('16',  'S12', 3),
    ('33',  'S08', 1), ('33',  'S09', 2),
    ('210', 'S10', 1), ('210', 'S08', 2), ('210', 'S11', 3),
    ('720', 'S02', 1), ('720', 'S04', 2), ('720', 'S11', 3), ('720', 'S12', 4),
    ('754', 'S01', 1), ('754', 'S03', 2), ('754', 'S02', 3),
    ('901', NULL,  1)
) ls(line_id, stop_id, stop_sequence);

CREATE TEMP TABLE _slots AS
WITH days AS (
    SELECT CAST(d AS DATE) AS service_date,
           date_diff('day', DATE '2026-11-02', CAST(d AS DATE)) AS day_idx
    FROM generate_series(TIMESTAMP '2026-11-02', TIMESTAMP '2026-11-08', INTERVAL 1 DAY) g(d)
),
raw AS (
    SELECT p.*, dir.direction_id, days.service_date, days.day_idx,
           unnest(generate_series(
               300 + dir.direction_id * 5,
               1530,
               CASE WHEN days.day_idx >= 5 THEN p.headway_min * 2 ELSE p.headway_min END
           )) AS start_min
    FROM _plan p
    CROSS JOIN (VALUES (0), (1)) dir(direction_id)
    CROSS JOIN days
)
SELECT *,
       ((CAST(start_min AS BIGINT) * 7919 + direction_id * 104729 + day_idx * 1299709
         + CAST(start_min AS BIGINT) * day_idx * 613
         + CAST(line_id AS BIGINT) * 15485863) % 10007) % 100 AS r,
       (start_min * 31 + day_idx * 7 + direction_id * 3 + CAST(line_id AS INTEGER)) % 97 AS r2,
       miss_pct + CASE
           WHEN line_id = '33'  AND day_idx BETWEEN 2 AND 4 THEN 12
           WHEN line_id = '210' AND day_idx IN (2, 5)       THEN -8
           WHEN line_id = '2'   AND day_idx = 3             THEN 6
           ELSE 0
       END AS day_miss_pct,
       service_date + to_minutes(CAST(start_min AS BIGINT)) AS start_ts
FROM raw;

CREATE TABLE trips AS
SELECT line_id || '-' || direction_id || '-' || strftime(service_date, '%m%d') || '-'
           || lpad(CAST(start_min // 60 AS VARCHAR), 2, '0')
           || lpad(CAST(start_min % 60 AS VARCHAR), 2, '0') AS trip_id,
       line_id,
       direction_id,
       service_date,
       CASE WHEN line_id IN ('4', '16') THEN CAST(start_min // 60 AS VARCHAR)
            ELSE lpad(CAST(start_min // 60 AS VARCHAR), 2, '0') END
           || ':' || lpad(CAST(start_min % 60 AS VARCHAR), 2, '0') || ':00' AS scheduled_start
FROM _slots;

CREATE TEMP TABLE _outcomes AS
SELECT s.*, t.trip_id,
       CASE WHEN r < cancel_pct                              THEN 'canceled'
            WHEN r < cancel_pct + day_miss_pct               THEN 'missed'
            WHEN r < cancel_pct + day_miss_pct + partial_pct THEN 'partial'
            ELSE 'ran' END AS outcome
FROM _slots s
JOIN trips t USING (line_id, direction_id, service_date)
WHERE t.scheduled_start = CASE WHEN s.line_id IN ('4', '16') THEN CAST(s.start_min // 60 AS VARCHAR)
                               ELSE lpad(CAST(s.start_min // 60 AS VARCHAR), 2, '0') END
                          || ':' || lpad(CAST(s.start_min % 60 AS VARCHAR), 2, '0') || ':00';

CREATE TABLE trip_outcomes AS
SELECT trip_id, service_date, outcome
FROM _outcomes
WHERE NOT (service_date = DATE '2026-11-08' AND start_min >= 22 * 60);

-- One posting per canceled trip, a re-post for some, and a withdrawal of the
-- latest posting for others (the cancellation was called off).
CREATE TABLE cancellations AS
WITH first_post AS (
    SELECT trip_id, service_date, r2,
           start_ts - to_minutes(CAST(10 + r2 % 50 AS BIGINT)) AS posted_at
    FROM _outcomes WHERE outcome = 'canceled'
),
postings AS (
    SELECT trip_id, service_date, r2, posted_at, r2 % 4 <> 0 AS is_latest FROM first_post
    UNION ALL
    SELECT trip_id, service_date, r2, posted_at + to_minutes(5), TRUE FROM first_post WHERE r2 % 4 = 0
)
SELECT row_number() OVER (ORDER BY posted_at, trip_id) AS alert_id,
       trip_id,
       service_date,
       posted_at,
       CASE WHEN is_latest AND r2 % 7 = 0 THEN posted_at + to_minutes(3) END AS withdrawn_at
FROM postings;

-- Pings every 30 s for line 754 on 2026-11-03: an hour for trips that ran,
-- half an hour for partial ones, ten minutes for canceled trips with r2 even.
CREATE TABLE vehicle_positions AS
WITH runs AS (
    SELECT o.*,
           'V' || CAST(7540 + (row_number() OVER (ORDER BY start_ts, direction_id)) % 20 AS VARCHAR) AS vehicle_id,
           CASE outcome WHEN 'ran' THEN 3570 WHEN 'partial' THEN 1770 ELSE 600 END AS last_offset
    FROM _outcomes o
    WHERE line_id = '754' AND service_date = DATE '2026-11-03'
      AND (outcome IN ('ran', 'partial') OR (outcome = 'canceled' AND r2 % 2 = 0))
),
pings AS (
    SELECT runs.*, unnest(generate_series(0, last_offset, 30)) AS offset_s FROM runs
),
kept AS (
    SELECT * FROM pings
    WHERE NOT (r2 % 5 = 0 AND offset_s > 1200 AND offset_s < 1440)
)
SELECT vehicle_id, trip_id,
       start_ts + to_seconds(CAST(offset_s AS BIGINT)) AS observed_at,
       start_ts + to_seconds(CAST(offset_s + 2 AS BIGINT)) AS received_at,
       round(34.05 + offset_s / 36000.0, 5) AS lat,
       round(-118.29 + offset_s / 72000.0, 5) AS lon
FROM kept
UNION ALL
SELECT vehicle_id, trip_id,
       start_ts + to_seconds(CAST(offset_s AS BIGINT)),
       start_ts + to_seconds(CAST(offset_s + 32 AS BIGINT)),
       round(34.05 + offset_s / 36000.0, 5),
       round(-118.29 + offset_s / 72000.0, 5)
FROM kept
WHERE r2 % 3 = 0 AND offset_s % 600 = 0;

-- One fetch a minute per feed on 2026-11-03, with three trip_updates outages
-- (15 minutes, 3 minutes, 1 minute) and one vehicle_positions outage.
CREATE TABLE fetch_log AS
SELECT f.feed,
       TIMESTAMP '2026-11-03 00:00:00' + to_minutes(m) AS fetched_at,
       NOT ((f.feed = 'trip_updates' AND (m BETWEEN 190 AND 204 OR m BETWEEN 842 AND 844 OR m = 846))
            OR (f.feed = 'vehicle_positions' AND m BETWEEN 570 AND 581)) AS ok
FROM (VALUES ('trip_updates'), ('vehicle_positions')) f(feed)
CROSS JOIN range(0, 1440) r(m);

DROP TABLE _plan;
DROP TABLE _slots;
DROP TABLE _outcomes;
