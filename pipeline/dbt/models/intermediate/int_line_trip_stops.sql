-- One row per stop visit of every trip in every schedule version that is ever in force:
-- (schedule_version, trip_id, stop_sequence). The line tables are built per version, so the API
-- can serve the version in force on the rider's own date (API spec section 4.3), including
-- across a service change, not just the version of the last synced day.
--
-- Each line x direction gets a main pattern: the stop list most trips run (ties: the longer list,
-- so a short turn never beats the full route; then alphabetical).
-- anchor_position places every visit on the main pattern's scale:
-- * a stop on the main pattern sits at its index there (first visit, so a loop's terminal is 1);
-- * any other stop is interpolated, by visit number within its own trip, between the main-pattern
--   stops before and after it. So a branch or a short turn that starts mid-route lands between the
--   right trunk stops, and keeps its own internal order. With no main stop after it, it goes
--   past the last one seen; with none before, before the next one; with none at all, it is
--   spread over 0..1.
with versions as (
    select version_id as schedule_version
    from {{ ref('dim_schedule_version') }}
    where ever_in_force
),

trips as (
    select t.schedule_version, t.trip_id, r.line, t.direction_id
    from {{ ref('dim_trips') }} as t
    inner join versions as v on t.schedule_version = v.schedule_version
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
        nullif(trim(st.stop_headsign), '') as stop_headsign,
        row_number() over (
            partition by tr.schedule_version, tr.trip_id order by st.stop_sequence
        ) as visit_no,
        count(*) over (partition by tr.schedule_version, tr.trip_id) as n_visits
    from trips as tr
    inner join {{ ref('dim_stop_times') }} as st
        on tr.schedule_version = st.schedule_version and tr.trip_id = st.trip_id
),

patterns as (
    select
        schedule_version, trip_id, line, direction_id,
        string_agg(stop_id, chr(31) order by stop_sequence) as pattern,
        count(*) as n_stops
    from visits
    group by schedule_version, trip_id, line, direction_id
),

main_patterns as (
    select schedule_version, line, direction_id, pattern, min(trip_id) as example_trip_id
    from patterns
    group by schedule_version, line, direction_id, pattern
    qualify row_number() over (
        partition by schedule_version, line, direction_id
        order by count(*) desc, max(n_stops) desc, pattern
    ) = 1
),

main_stops as (
    select m.schedule_version, m.line, m.direction_id, v.stop_id, min(v.visit_no) as main_index
    from main_patterns as m
    inner join visits as v
        on m.schedule_version = v.schedule_version and m.example_trip_id = v.trip_id
    group by m.schedule_version, m.line, m.direction_id, v.stop_id
),

placed as (
    select
        v.*,
        p.pattern,
        mp.pattern is not null as is_main_pattern,
        ms.main_index
    from visits as v
    inner join patterns as p on v.schedule_version = p.schedule_version and v.trip_id = p.trip_id
    left join main_patterns as mp
        on p.schedule_version = mp.schedule_version and p.line = mp.line
        and p.direction_id = mp.direction_id and p.pattern = mp.pattern
    left join main_stops as ms
        on v.schedule_version = ms.schedule_version and v.line = ms.line
        and v.direction_id = ms.direction_id and v.stop_id = ms.stop_id
),

neighbours as (
    select
        *,
        last_value(main_index ignore nulls) over before as prev_index,
        last_value(case when main_index is not null then visit_no end ignore nulls) over before
            as prev_visit,
        first_value(main_index ignore nulls) over after as next_index,
        first_value(case when main_index is not null then visit_no end ignore nulls) over after
            as next_visit
    from placed
    window
        before as (
            partition by schedule_version, trip_id order by visit_no
            rows between unbounded preceding and 1 preceding
        ),
        after as (
            partition by schedule_version, trip_id order by visit_no
            rows between 1 following and unbounded following
        )
)

select
    schedule_version,
    trip_id,
    stop_sequence,
    stop_id,
    stop_headsign,
    line,
    direction_id,
    pattern,
    is_main_pattern,
    main_index,
    case
        when main_index is not null then cast(main_index as double)
        when prev_index is not null and next_index is not null
            then prev_index
                + (visit_no - prev_visit) * (next_index - prev_index) / (next_visit - prev_visit)
        when next_index is not null then next_index - (next_visit - visit_no) / next_visit
        when prev_index is not null
            then prev_index + (visit_no - prev_visit) / (n_visits - prev_visit + 1)
        else visit_no / (n_visits + 1)
    end as anchor_position
from neighbours
