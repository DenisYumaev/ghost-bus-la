-- One row per trip x service date ever marked CANCELED: (trip_id, service_date)
-- (pipeline spec, sections 6.1 and 8).
--
-- State is one value per fetch: the relationship of the report stg_trip_reports chose for
-- that trip-fetch (newest by Metro's timestamp), the same choice stg_trip_updates uses.
-- Metro re-stamps a canceled entry on every fetch (docs/research/duplicate-trip-reports.md:
-- 1,107 of 1,111 canceled entities changed timestamp between fetches), so a lingering
-- cancellation is Metro restating it, not a stale row; but two live entities for one trip
-- can both refresh, so ordering raw reports could interleave them into fake episodes.
-- One chosen state per fetch, ordered by fetch time, avoids that. All times are our fetch
-- times (one clock).
--
-- - first_seen_at: first fetch of the *final* cancellation episode (CANCELED fetches after
--   the last SCHEDULED fetch before the last CANCELED one). For canceled -> scheduled ->
--   canceled, advance notice runs from the second: the first was retracted.
-- - first_ever_canceled_at: first fetch with any CANCELED report, chosen or not.
-- - reinstated_at: first fetch after the last CANCELED one whose state is SCHEDULED; NULL if
--   none. Whether that withdraws the cancellation depends on the scheduled start (alerts
--   spec: only while it's still ahead), applied in int_trip_observations.
-- - last_seen_at / n_snapshots: fetches whose state was CANCELED. Not "still canceled at":
--   use reinstated_at for that.
-- Only SCHEDULED ends an episode; other relationships (ADDED, DELETED, ...) don't occur in
-- Metro's feed so far (accepted_values warns if they appear) and are left to an ADR.
with reports as (
    select * from {{ ref('stg_trip_reports') }}
),

states as (
    select trip_id, service_date, fetched_at, trip_schedule_relationship as state,
           route_id, direction_id, start_time
    from reports
    where is_chosen
),

canceled_trips as (
    select
        trip_id,
        service_date,
        max(fetched_at) as last_seen_at,
        count(*) as n_snapshots,
        any_value(route_id) as route_id,
        any_value(direction_id) as direction_id,
        any_value(start_time) as start_time
    from states
    where state = 'CANCELED'
    group by trip_id, service_date
),

ever as (
    select trip_id, service_date, min(fetched_at) as first_ever_canceled_at
    from reports
    where trip_schedule_relationship = 'CANCELED'
    group by trip_id, service_date
),

bounds as (
    select
        c.trip_id,
        c.service_date,
        max(s.fetched_at) filter (where s.state = 'SCHEDULED' and s.fetched_at < c.last_seen_at)
            as scheduled_before_last_cancel,
        min(s.fetched_at) filter (where s.state = 'SCHEDULED' and s.fetched_at > c.last_seen_at)
            as reinstated_at
    from canceled_trips as c
    join states as s using (trip_id, service_date)
    group by c.trip_id, c.service_date
),

final_episode as (
    select s.trip_id, s.service_date, min(s.fetched_at) as first_seen_at
    from states as s
    join bounds as b using (trip_id, service_date)
    where s.state = 'CANCELED'
      and (b.scheduled_before_last_cancel is null or s.fetched_at > b.scheduled_before_last_cancel)
    group by s.trip_id, s.service_date
)

select
    c.trip_id,
    c.service_date,
    c.route_id,
    c.direction_id,
    c.start_time,
    f.first_seen_at,
    e.first_ever_canceled_at,
    c.last_seen_at,
    c.n_snapshots,
    b.reinstated_at,
    b.reinstated_at is not null as reinstated
from canceled_trips as c
join bounds as b using (trip_id, service_date)
join final_episode as f using (trip_id, service_date)
join ever as e using (trip_id, service_date)
