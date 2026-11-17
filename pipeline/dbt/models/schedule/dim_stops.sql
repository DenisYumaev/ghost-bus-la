select schedule_version, stop_id, stop_code, stop_name, stop_lat, stop_lon
from {{ ref('src_gtfs_stops') }}
