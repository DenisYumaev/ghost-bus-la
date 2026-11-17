-- One row per vehicle report: (vehicle_id, vehicle_ts) (pipeline spec, section 6.1).
-- A vehicle's report repeats in every snapshot until it sends a new one, so the same
-- (vehicle_id, vehicle_ts) appears in many snapshots; keep the first sighting and count them.
-- Coordinates were range-checked in decode, which quarantines impossible ones.
-- service_date is the trip descriptor's start_date (GTFS-rt), NULL when not on a trip.
with positions as (
    select * from {{ ref('src_vehicle_position') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by vehicle_id, vehicle_ts order by fetched_at, snapshot_sha
        ) as nth_sighting,
        count(*) over (partition by vehicle_id, vehicle_ts) as n_snapshots
    from positions
)

select
    vehicle_id,
    vehicle_ts,
    fetched_at as first_fetched_at,
    n_snapshots,
    trip_id,
    route_id,
    direction_id,
    start_date as service_date,
    start_time,
    coalesce(trip_schedule_relationship, 'SCHEDULED') as trip_schedule_relationship,
    lat,
    lon,
    bearing,
    speed,
    current_stop_sequence,
    stop_id,
    current_status
from ranked
where nth_sighting = 1
