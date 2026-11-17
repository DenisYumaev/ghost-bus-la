{{ config(severity='warn') }}
-- Mixed weekly patterns (a weekday plus a weekend day, or Saturday plus Sunday) don't vote in
-- int_service_day_types. Metro's schedule has none today; warn if a new version adds them, since
-- many of a date's trips could then fall back to the calendar day.
select schedule_version, service_id
from {{ ref('dim_calendar') }}
where (saturday + sunday > 0 and monday + tuesday + wednesday + thursday + friday > 0)
   or (saturday = 1 and sunday = 1)
