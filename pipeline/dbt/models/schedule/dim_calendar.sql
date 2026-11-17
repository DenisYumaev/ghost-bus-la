-- Weekly service patterns per schedule version; exceptions are in dim_calendar_dates.
select
    schedule_version, service_id,
    monday, tuesday, wednesday, thursday, friday, saturday, sunday,
    start_date, end_date
from {{ ref('src_gtfs_calendar') }}
