-- One row per service date in scope: (service_date), with its day type for reliability cells
-- (pipeline spec, section 6.3). The day type is the weekly pattern most of the date's scheduled
-- trips come from, so the schedule decides, not the calendar: Metro runs Sunday service on
-- holidays (Thanksgiving 2026 adds the `…_Sunday` service IDs in calendar_dates), and those
-- dates count as sundays (on 2026-11-26 the schedule removes all 12 `…_Weekday` IDs and adds the
-- 12 `…_Sunday` ones; the same on Jul 4 and Sep 7: docs/research/holiday-service.md). Only pure
-- patterns vote: Monday-Friday days only, Saturday only, or Sunday only. A mixed pattern (daily,
-- or Saturday plus Sunday) says nothing about which kind of day this is, and neither do services
-- missing from calendar.txt. A date with no voting trips falls back to its calendar day. Ties go
-- to the alphabetically first pattern.
with trip_patterns as (
    select
        e.service_date,
        case
            when c.saturday + c.sunday = 0
                and c.monday + c.tuesday + c.wednesday + c.thursday + c.friday > 0 then 'weekday'
            when c.monday + c.tuesday + c.wednesday + c.thursday + c.friday = 0
                and c.saturday = 1 and c.sunday = 0 then 'saturday'
            when c.monday + c.tuesday + c.wednesday + c.thursday + c.friday = 0
                and c.saturday = 0 and c.sunday = 1 then 'sunday'
        end as pattern
    from {{ ref('int_schedule_expanded') }} as e
    inner join {{ ref('dim_calendar') }} as c
        on e.schedule_version = c.schedule_version
        and e.service_id = c.service_id
),

votes as (
    select service_date, pattern, count(*) as n_trips
    from trip_patterns
    where pattern is not null
    group by service_date, pattern
),

winner as (
    select service_date, pattern
    from votes
    qualify row_number() over (partition by service_date order by n_trips desc, pattern) = 1
)

select
    d.service_date,
    coalesce(
        w.pattern,
        case d.iso_dow when 6 then 'saturday' when 7 then 'sunday' else 'weekday' end
    ) as day_type,
    case when w.pattern is null then 'calendar' else 'schedule' end as day_type_source
from {{ ref('int_service_dates') }} as d
left join winner as w on d.service_date = w.service_date
