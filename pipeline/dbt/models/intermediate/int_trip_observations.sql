-- One row per scheduled trip per service date: (service_date, schedule_version, trip_id)
-- (pipeline spec, sections 6.2 and 8). What the realtime feeds showed about each trip that
-- should run, inside its observation window: scheduled start - var('window_before_start_min')
-- to scheduled end + var('window_after_end_min').
--
-- - Vehicle positions matched exactly on (trip_id, service_date) (int_trip_crosswalk):
--   n_positions, vehicle_ids, first and last seen, max_stop_sequence (the furthest
--   current_stop_sequence a vehicle reported; trip-update stop sequences are predictions of
--   the remaining stops, so they'd put every trip near its last stop).
-- - Trip updates: only each fetch's chosen report (stg_trip_reports.is_chosen); a
--   non-chosen duplicate can be a stale SCHEDULED report still carrying a vehicle next to a
--   newer cancellation. n_updates_with_vehicle counts chosen SCHEDULED reports with a vehicle.
-- - observed_running (spec section 8): a matched position, or a chosen SCHEDULED trip update
--   with a vehicle, in the window. A CANCELED update is not an observation.
-- - rt_canceled: marked CANCELED in trip updates and not withdrawn before the scheduled
--   start. Alerts spec: a cancellation is withdrawn only if the trip returns to SCHEDULED
--   while its start is still ahead (4 of 121 reinstatements on Nov 15 came later).
with scheduled as (
    select
        service_date, schedule_version, trip_id, line, route_id, direction_id, block_id,
        n_stops, sched_start_utc, sched_end_utc,
        sched_start_utc - {{ var('window_before_start_min') }} * interval 1 minute as window_start,
        sched_end_utc + {{ var('window_after_end_min') }} * interval 1 minute as window_end
    from {{ ref('int_schedule_expanded') }}
),

positions as (
    select
        s.service_date, s.schedule_version, s.trip_id,
        count(*) as n_positions,
        list(distinct p.vehicle_id order by p.vehicle_id) as vehicle_ids,
        min(p.vehicle_ts) as first_position_at,
        max(p.vehicle_ts) as last_position_at,
        max(p.current_stop_sequence) as max_stop_sequence
    from scheduled as s
    join {{ ref('stg_vehicle_positions') }} as p
        on p.trip_id = s.trip_id and p.service_date = s.service_date
        and p.vehicle_ts between s.window_start and s.window_end
    group by s.service_date, s.schedule_version, s.trip_id
),

updates as (
    select
        s.service_date, s.schedule_version, s.trip_id,
        count(*) filter (where r.trip_schedule_relationship = 'SCHEDULED') as n_updates,
        count(*) filter (
            where r.trip_schedule_relationship = 'SCHEDULED' and r.vehicle_id is not null
        ) as n_updates_with_vehicle,
        min(r.fetched_at) filter (
            where r.trip_schedule_relationship = 'SCHEDULED' and r.vehicle_id is not null
        ) as first_update_with_vehicle_at,
        max(r.fetched_at) filter (
            where r.trip_schedule_relationship = 'SCHEDULED' and r.vehicle_id is not null
        ) as last_update_with_vehicle_at
    from scheduled as s
    join {{ ref('stg_trip_reports') }} as r
        on r.trip_id = s.trip_id and r.service_date = s.service_date
        and r.is_chosen
        and r.fetched_at between s.window_start and s.window_end
    group by s.service_date, s.schedule_version, s.trip_id
),

cancellations as (
    select trip_id, service_date, first_seen_at, reinstated_at
    from {{ ref('stg_cancellations') }}
)

select
    s.service_date,
    s.schedule_version,
    s.trip_id,
    s.line,
    s.route_id,
    s.direction_id,
    s.block_id,
    s.n_stops,
    s.sched_start_utc,
    s.sched_end_utc,
    s.window_start,
    s.window_end,
    coalesce(p.n_positions, 0) as n_positions,
    p.vehicle_ids,
    p.max_stop_sequence,
    coalesce(u.n_updates, 0) as n_updates,
    coalesce(u.n_updates_with_vehicle, 0) as n_updates_with_vehicle,
    least(p.first_position_at, u.first_update_with_vehicle_at) as first_seen_utc,
    greatest(p.last_position_at, u.last_update_with_vehicle_at) as last_seen_utc,
    coalesce(p.n_positions, 0) > 0 or coalesce(u.n_updates_with_vehicle, 0) > 0
        as observed_running,
    c.trip_id is not null
        and (c.reinstated_at is null or c.reinstated_at >= s.sched_start_utc) as rt_canceled,
    c.first_seen_at as canceled_first_seen_at,
    c.reinstated_at
from scheduled as s
left join positions as p using (service_date, schedule_version, trip_id)
left join updates as u using (service_date, schedule_version, trip_id)
left join cancellations as c
    on c.trip_id = s.trip_id and c.service_date = s.service_date
