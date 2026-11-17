-- Warning: one vehicle report (vehicle_id, vehicle_ts) seen with more than one trip_id. The
-- dedupe keeps the first sighting, so the other trip would lose that position.
{{ config(severity='warn') }}
select vehicle_id, vehicle_ts, n_trips
from {{ ref('stg_vehicle_positions') }}
where n_trips > 1
