-- One row per trip x service date ever marked CANCELED in trip updates: (trip_id, service_date)
-- (pipeline spec, sections 6.1 and 8). first_seen_at starts the advance-notice clock; a trip
-- is `reinstated` if a SCHEDULED trip update for it arrived after the last CANCELED one
-- (it was returned to service). Canceled entries linger for hours (day-1 probe), so
-- n_snapshots counts distinct fetches, not rows.
with updates as (
    select * from {{ ref('stg_trip_updates') }}
),

canceled as (
    select
        trip_id,
        service_date,
        min(fetched_at) as first_seen_at,
        max(fetched_at) as last_seen_at,
        count(distinct fetched_at) as n_snapshots,
        any_value(route_id) as route_id,
        any_value(direction_id) as direction_id,
        any_value(start_time) as start_time
    from updates
    where trip_schedule_relationship = 'CANCELED'
    group by trip_id, service_date
),

scheduled_after as (
    select u.trip_id, u.service_date, max(u.fetched_at) as last_scheduled_at
    from updates as u
    join canceled as c using (trip_id, service_date)
    where u.trip_schedule_relationship = 'SCHEDULED'
    group by u.trip_id, u.service_date
)

select
    c.trip_id,
    c.service_date,
    c.route_id,
    c.direction_id,
    c.start_time,
    c.first_seen_at,
    c.last_seen_at,
    c.n_snapshots,
    coalesce(s.last_scheduled_at > c.last_seen_at, false) as reinstated
from canceled as c
left join scheduled_after as s using (trip_id, service_date)
