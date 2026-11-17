-- A trip's last stop isn't scheduled before its first.
select service_date, schedule_version, trip_id, sched_start_utc, sched_end_utc
from {{ ref('int_schedule_expanded') }}
where sched_end_utc < sched_start_utc
