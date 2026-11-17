-- One row per stop prediction of the chosen report per trip-fetch:
-- (trip_id, service_date, fetched_at, stop_key, stop_id_key) (pipeline spec, section 6.1;
-- grain on fetched_at because a duplicate fetch repeats its snapshot's rows with the same
-- feed_ts). Only the report stg_trip_reports chose for each trip-fetch is kept.
-- is_trip_level marks the single row of a report with no stop-time updates (a
-- cancellation); a stop-time update with only a stop_id gets stop_key -1 but isn't one.
--
-- A view: about 40 million rows a day, so materializing would copy them all. Consumers that
-- need one row per trip per fetch use stg_trip_reports instead.
-- NULL scheduleRelationship is GTFS-rt's default, SCHEDULED (spec section 3).
{{ config(materialized='view') }}

with updates as (
    select * from {{ ref('src_trip_update') }}
),

chosen as (
    select trip_id, service_date, fetched_at, entity_key, n_reports
    from {{ ref('stg_trip_reports') }}
    where is_chosen
)

select
    u.trip_id,
    u.start_date as service_date,
    coalesce(u.stop_sequence, -1) as stop_key,
    coalesce(u.stop_id, '') as stop_id_key,
    u.fetched_at,
    u.feed_ts,
    u.snapshot_sha,
    u.entity_id,
    u.route_id,
    u.direction_id,
    u.start_time,
    coalesce(u.trip_schedule_relationship, 'SCHEDULED') as trip_schedule_relationship,
    u.vehicle_id,
    u.entity_ts,
    c.n_reports,
    u.stop_sequence is null and u.stop_id is null as is_trip_level,
    u.stop_sequence,
    u.stop_id,
    u.arrival_ts,
    u.departure_ts,
    coalesce(u.stop_schedule_relationship, 'SCHEDULED') as stop_schedule_relationship
from updates as u
join chosen as c
    on c.trip_id = u.trip_id
    and c.service_date = u.start_date
    and c.fetched_at = u.fetched_at
    and c.entity_key = coalesce(u.entity_id, '_noid')
