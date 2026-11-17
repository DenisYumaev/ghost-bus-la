-- One row per stop a line x direction serves: (line, direction_id, stop_id). Feeds
-- serving.line_stop: stop pickers and commute validation (API spec, sections 4.3 and 7).
-- Every stop any trip serves is listed, including branches and short turns. stop_order ranks
-- stops by their average relative position along the trips that serve them, so a branch's stops
-- fall in place between the trunk's; ties go to the stop more trips serve, then stop_id. A loop
-- route's repeated stop appears once.
with stops as (
    select
        line,
        direction_id,
        stop_id,
        any_value(schedule_version) as schedule_version,
        avg(rel_position) as avg_position,
        count(distinct trip_id) as n_trips,
        bool_or(is_main_pattern) as in_main_pattern
    from {{ ref('int_line_trip_stops') }}
    group by line, direction_id, stop_id
)

select
    s.line,
    s.direction_id,
    row_number() over (
        partition by s.line, s.direction_id order by s.avg_position, s.n_trips desc, s.stop_id
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
