-- One row per scheduled trip per service date: (service_date, schedule_version, trip_id)
-- (pipeline spec, section 6.2). Every trip that should run, from the version in force.
--
-- A service_id runs on a date if its calendar row covers the date and has that weekday's
-- flag, unless calendar_dates removes it (exception_type 2); calendar_dates can also add it
-- (exception_type 1) on any date. Times use the GTFS rule (noon minus 12 h, Los Angeles;
-- macro gtfs_to_utc), so a 25:10 trip lands on the next calendar day. The start is the first
-- stop's departure (else arrival); the end is the last stop's arrival (else departure).
with days as (
    select service_date, schedule_version, iso_dow
    from {{ ref('int_service_dates') }}
    where schedule_version is not null
),

weekly as (
    select d.service_date, d.schedule_version, c.service_id
    from days as d
    join {{ ref('dim_calendar') }} as c
        on c.schedule_version = d.schedule_version
        and d.service_date between c.start_date and c.end_date
        and case d.iso_dow
            when 1 then c.monday when 2 then c.tuesday when 3 then c.wednesday
            when 4 then c.thursday when 5 then c.friday when 6 then c.saturday
            when 7 then c.sunday
        end = 1
),

exceptions as (
    select d.service_date, d.schedule_version, x.service_id, x.exception_type
    from days as d
    join {{ ref('dim_calendar_dates') }} as x
        on x.schedule_version = d.schedule_version and x.service_date = d.service_date
),

active as (
    select service_date, schedule_version, service_id from weekly
    union
    select service_date, schedule_version, service_id from exceptions where exception_type = 1
    except
    select service_date, schedule_version, service_id from exceptions where exception_type = 2
),

trip_stops as (
    select
        schedule_version,
        trip_id,
        count(*) as n_stops,
        arg_min(stop_id, stop_sequence) as first_stop_id,
        arg_min(coalesce(departure_s, arrival_s), stop_sequence) as start_s,
        arg_max(coalesce(arrival_s, departure_s), stop_sequence) as end_s
    from {{ ref('dim_stop_times') }}
    group by schedule_version, trip_id
)

select
    a.service_date,
    t.schedule_version,
    t.trip_id,
    t.route_id,
    r.line,
    t.direction_id,
    t.block_id,
    t.service_id,
    s.first_stop_id,
    s.n_stops,
    s.start_s,
    s.end_s,
    {{ gtfs_to_utc('a.service_date', 's.start_s') }} as sched_start_utc,
    {{ gtfs_to_utc('a.service_date', 's.end_s') }} as sched_end_utc
from active as a
join {{ ref('dim_trips') }} as t
    on t.schedule_version = a.schedule_version and t.service_id = a.service_id
join trip_stops as s
    on s.schedule_version = t.schedule_version and s.trip_id = t.trip_id
join {{ ref('dim_routes') }} as r
    on r.schedule_version = t.schedule_version and r.route_id = t.route_id
