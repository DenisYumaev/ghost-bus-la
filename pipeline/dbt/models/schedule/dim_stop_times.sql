-- One row per trip stop per schedule version. arrival_s/departure_s are GTFS seconds since
-- noon minus 12 h on the service date (decoded and checked in ghostbus_decode).
select
    schedule_version,
    trip_id,
    stop_sequence,
    stop_id,
    arrival_time,
    arrival_s,
    departure_time,
    departure_s,
    stop_headsign,
    timepoint
from {{ ref('src_gtfs_stop_times') }}
