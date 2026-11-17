-- Service added (exception_type 1) or removed (2) on one date, per schedule version.
select schedule_version, service_id, "date" as service_date, exception_type
from {{ ref('src_gtfs_calendar_dates') }}
