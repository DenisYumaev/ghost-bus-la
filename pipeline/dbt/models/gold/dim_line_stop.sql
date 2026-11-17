-- One row per stop a line x direction serves, per schedule version in force at some point:
-- (schedule_version, line, direction_id, stop_id). Feeds serving.line_stop: stop pickers and
-- commute validation against the version in force on the rider's date (API spec, sections 4.3
-- and 7). Every stop any trip serves is listed, including branches and short turns. stop_order
-- ranks stops on the main pattern's scale (int_line_trip_stops.anchor_position): main-pattern
-- stops in route order, others between the trunk stops around them. A stop visited twice in a
-- trip (a loop's terminal) uses its first visit. Ties: more trips first, then stop_id.
with per_trip as (
    select schedule_version, line, direction_id, stop_id, trip_id,
           min(anchor_position) as position, bool_or(is_main_pattern) as on_main_trip
    from {{ ref('int_line_trip_stops') }}
    group by schedule_version, line, direction_id, stop_id, trip_id
),

stops as (
    select
        schedule_version, line, direction_id, stop_id,
        avg(position) as avg_position,
        count(*) as n_trips,
        bool_or(on_main_trip) as in_main_pattern
    from per_trip
    group by schedule_version, line, direction_id, stop_id
)

select
    s.schedule_version,
    s.line,
    s.direction_id,
    row_number() over (
        partition by s.schedule_version, s.line, s.direction_id
        -- Rounded: a float average can differ in its last bits between runs (parallel sums),
        -- which must not flip the order of two stops at the same true position.
        order by round(s.avg_position, 9), s.n_trips desc, s.stop_id
    ) as stop_order,
    s.stop_id,
    d.stop_code,
    d.stop_name,
    d.stop_lat,
    d.stop_lon,
    s.n_trips,
    s.in_main_pattern
from stops as s
left join {{ ref('dim_stops') }} as d
    on s.schedule_version = d.schedule_version and s.stop_id = d.stop_id
