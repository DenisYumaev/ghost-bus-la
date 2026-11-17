-- One row per trip with an outcome, in the reliability scope: (service_date, schedule_version,
-- trip_id), with what every aggregate groups by (pipeline spec sections 6.3 and 8; ADR-025).
-- day_type follows the service date (from the schedule); hour_local is the America/Los_Angeles
-- clock hour of the scheduled start, so a 25:30 trip is hour 1 of its own service date. Trips
-- are kept unless is_metro_operated is false: NULL until the contracted-lines seed (ADR-024
-- decision 6), after which contracted lines drop out of every aggregate (SPEC section 2).
select
    o.service_date,
    o.schedule_version,
    o.trip_id,
    o.line,
    o.direction_id,
    d.day_type,
    cast(extract(hour from o.sched_start_utc at time zone 'America/Los_Angeles') as integer)
        as hour_local,
    o.outcome,
    o.announced
from {{ ref('fct_trip_outcomes') }} as o
inner join {{ ref('int_service_day_types') }} as d on o.service_date = d.service_date
where o.is_metro_operated is distinct from false
