-- location_type and parent_station: stations and entrances (location_type 1-4) aren't
-- boardable stops; the rider lookup filters on them.
select
    schedule_version, stop_id, stop_code, stop_name, stop_lat, stop_lon,
    location_type, parent_station
from {{ ref('src_gtfs_stops') }}
