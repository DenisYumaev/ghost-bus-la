-- One row per trip x stop x fetch: (trip_id, service_date, stop_key, fetched_at)
-- (pipeline spec, section 6.1; grain on fetched_at because a duplicate fetch repeats its
-- snapshot's rows with the same feed_ts). stop_key is stop_sequence, or -1 for the one
-- trip-level row a trip with no stop-time updates gets (a cancellation).
--
-- One report per trip per fetch: Metro sometimes publishes the same trip twice in one
-- snapshot under different entity IDs, typically a stale report without a vehicle next to a
-- newer one with it (Nov 14-16: 18,323 of 14.6 million trip-fetches, 266 of them with one
-- CANCELED and one SCHEDULED). The newest report (entity_ts, then the one with a vehicle)
-- wins; n_reports keeps the count visible.
--
-- A view: about 40 million rows a day, so materializing would copy them all.
-- NULL scheduleRelationship is GTFS-rt's default, SCHEDULED (spec section 3).
{{ config(materialized='view') }}

with updates as (
    select * from {{ ref('src_trip_update') }}
),

ranked as (
    select
        *,
        dense_rank() over (
            partition by trip_id, start_date, fetched_at
            order by entity_ts desc nulls last, vehicle_id nulls last
        ) as report_rank
    from updates
),

counted as (
    select
        *,
        max(report_rank) over (partition by trip_id, start_date, fetched_at) as n_reports
    from ranked
)

select
    trip_id,
    start_date as service_date,
    coalesce(stop_sequence, -1) as stop_key,
    fetched_at,
    feed_ts,
    snapshot_sha,
    route_id,
    direction_id,
    start_time,
    coalesce(trip_schedule_relationship, 'SCHEDULED') as trip_schedule_relationship,
    vehicle_id,
    entity_ts,
    n_reports,
    stop_sequence,
    stop_id,
    arrival_ts,
    departure_ts,
    coalesce(stop_schedule_relationship, 'SCHEDULED') as stop_schedule_relationship
from counted
where report_rank = 1
