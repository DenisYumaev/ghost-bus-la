-- One row per trip per schedule version. Trip IDs change at every service change, so the
-- key is (schedule_version, trip_id), never trip_id alone (ADR-001 decision 4).
select
    schedule_version,
    trip_id,
    route_id,
    service_id,
    direction_id,
    nullif(block_id, '') as block_id,  -- 713 of Metro's trips have none
    shape_id
from {{ ref('src_gtfs_trips') }}
