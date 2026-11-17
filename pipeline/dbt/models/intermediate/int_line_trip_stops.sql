-- One row per stop visit of every trip in the schedule version in force on the last synced
-- service date: (trip_id, stop_sequence). The line tables describe "the line as it runs now", so
-- they read that one version. Each trip gets its stop pattern (the ordered stop list) and each
-- visit its relative position along the trip, 0 at the first stop and 1 at the last. The main
-- pattern of a line x direction is the one most trips run (ties: the alphabetically first).
with current_version as (
    select schedule_version
    from {{ ref('int_service_dates') }}
    qualify row_number() over (order by service_date desc) = 1
),

trips as (
    select t.schedule_version, t.trip_id, r.line, t.direction_id
    from {{ ref('dim_trips') }} as t
    inner join current_version as v on t.schedule_version = v.schedule_version
    inner join {{ ref('dim_routes') }} as r
        on t.schedule_version = r.schedule_version and t.route_id = r.route_id
),

visits as (
    select
        tr.schedule_version,
        tr.trip_id,
        tr.line,
        tr.direction_id,
        st.stop_sequence,
        st.stop_id,
        st.stop_headsign,
        row_number() over (partition by tr.trip_id order by st.stop_sequence) as visit_no,
        count(*) over (partition by tr.trip_id) as n_visits
    from trips as tr
    inner join {{ ref('dim_stop_times') }} as st
        on tr.schedule_version = st.schedule_version and tr.trip_id = st.trip_id
),

patterns as (
    select trip_id, line, direction_id, string_agg(stop_id, '>' order by stop_sequence) as pattern
    from visits
    group by trip_id, line, direction_id
),

main_patterns as (
    select line, direction_id, pattern
    from patterns
    group by line, direction_id, pattern
    qualify row_number() over (
        partition by line, direction_id order by count(*) desc, pattern
    ) = 1
)

select
    v.schedule_version,
    v.trip_id,
    v.stop_sequence,
    v.stop_id,
    v.stop_headsign,
    v.line,
    v.direction_id,
    p.pattern,
    m.pattern is not null as is_main_pattern,
    case when v.n_visits > 1 then (v.visit_no - 1) / (v.n_visits - 1) else 0.0 end as rel_position
from visits as v
inner join patterns as p on v.trip_id = p.trip_id
left join main_patterns as m
    on p.line = m.line and p.direction_id = m.direction_id and p.pattern = m.pattern
