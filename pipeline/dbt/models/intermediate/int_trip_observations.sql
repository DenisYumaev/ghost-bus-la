-- One row per scheduled trip per service date: (service_date, schedule_version, trip_id)
-- (pipeline spec, sections 6.2 and 8). What the realtime feeds showed about each trip that
-- should run, inside its observation window: scheduled start - var('window_before_start_min')
-- to scheduled end + var('window_after_end_min').
--
-- Every feed reaches the scheduled trip through int_trip_crosswalk (hard rule 6): realtime
-- (trip_id, service_date) -> scheduled_trip_id, matched only.
--
-- - Vehicle positions whose trip descriptor is SCHEDULED: n_positions, vehicle_ids, first and
--   last seen (vehicle clock), last_position_fetched_at (our clock, comparable with
--   cancellation times), max_stop_sequence (furthest current_stop_sequence; IN_TRANSIT_TO
--   names the next stop, so it can lead by one; tuned with the thresholds, spec section 8).
--   The *_after_start columns count only positions at or after the scheduled start, so a bus
--   waiting at the first stop before departure is distinguishable. n_positions_ambiguous
--   counts reports that named more than one trip (stg_vehicle_positions.n_trips > 1).
-- - Trip updates: only each fetch's chosen report (a non-chosen duplicate can be a stale
--   SCHEDULED report still carrying a vehicle next to a newer cancellation). n_updates counts
--   chosen SCHEDULED reports; n_updates_with_vehicle those with a vehicle.
-- - observed_running (spec section 8): a matched SCHEDULED position, or a chosen SCHEDULED
--   trip update with a vehicle, in the window. A CANCELED report is not an observation.
-- - rt_canceled: marked CANCELED and not reinstated before the scheduled start (pipeline
--   spec section 8; the alerts spec also withdraws on leaving the stream, an open question).
with scheduled as (
    select
        service_date, schedule_version, trip_id, line, route_id, direction_id, block_id,
        n_stops, sched_start_utc, sched_end_utc,
        sched_start_utc - {{ var('window_before_start_min') }} * interval 1 minute as window_start,
        sched_end_utc + {{ var('window_after_end_min') }} * interval 1 minute as window_end
    from {{ ref('int_schedule_expanded') }}
),

matched as (
    select trip_id, service_date, schedule_version, scheduled_trip_id
    from {{ ref('int_trip_crosswalk') }}
    where match_method <> 'unmatched'
),

positions as (
    select
        s.service_date, s.schedule_version, s.trip_id,
        count(*) as n_positions,
        count(*) filter (where p.vehicle_ts >= s.sched_start_utc) as n_positions_after_start,
        count(*) filter (where p.n_trips > 1) as n_positions_ambiguous,
        list(distinct p.vehicle_id order by p.vehicle_id) as vehicle_ids,
        min(p.vehicle_ts) as first_position_at,
        max(p.vehicle_ts) as last_position_at,
        max(p.first_fetched_at) as last_position_fetched_at,
        max(p.current_stop_sequence) as max_stop_sequence,
        max(p.current_stop_sequence) filter (where p.vehicle_ts >= s.sched_start_utc)
            as max_stop_sequence_after_start
    from scheduled as s
    join matched as m
        on m.service_date = s.service_date and m.schedule_version = s.schedule_version
        and m.scheduled_trip_id = s.trip_id
    join {{ ref('stg_vehicle_positions') }} as p
        on p.trip_id = m.trip_id and p.service_date = m.service_date
        and p.trip_schedule_relationship = 'SCHEDULED'
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
        list(distinct r.vehicle_id order by r.vehicle_id) filter (
            where r.trip_schedule_relationship = 'SCHEDULED' and r.vehicle_id is not null
        ) as update_vehicle_ids,
        min(r.fetched_at) filter (
            where r.trip_schedule_relationship = 'SCHEDULED' and r.vehicle_id is not null
        ) as first_update_with_vehicle_at,
        max(r.fetched_at) filter (
            where r.trip_schedule_relationship = 'SCHEDULED' and r.vehicle_id is not null
        ) as last_update_with_vehicle_at
    from scheduled as s
    join matched as m
        on m.service_date = s.service_date and m.schedule_version = s.schedule_version
        and m.scheduled_trip_id = s.trip_id
    join {{ ref('stg_trip_reports') }} as r
        on r.trip_id = m.trip_id and r.service_date = m.service_date
        and r.is_chosen
        and r.fetched_at between s.window_start and s.window_end
    group by s.service_date, s.schedule_version, s.trip_id
),

cancellations as (
    select m.service_date, m.schedule_version, m.scheduled_trip_id as trip_id,
           c.first_seen_at, c.reinstated_at
    from {{ ref('stg_cancellations') }} as c
    join matched as m on m.trip_id = c.trip_id and m.service_date = c.service_date
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
    coalesce(p.n_positions_after_start, 0) as n_positions_after_start,
    coalesce(p.n_positions_ambiguous, 0) as n_positions_ambiguous,
    p.vehicle_ids,
    p.max_stop_sequence,
    p.max_stop_sequence_after_start,
    p.last_position_fetched_at,
    coalesce(u.n_updates, 0) as n_updates,
    coalesce(u.n_updates_with_vehicle, 0) as n_updates_with_vehicle,
    u.update_vehicle_ids,
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
left join cancellations as c using (service_date, schedule_version, trip_id)
