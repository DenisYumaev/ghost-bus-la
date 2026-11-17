-- Along each line x direction, stops on the main pattern appear in the order the main pattern
-- visits them: stop_order rises with the main-pattern index. Catches any ordering that lets a
-- short turn or branch pull a trunk stop out of place.
with main as (
    select s.schedule_version, s.line, s.direction_id, s.stop_order, i.main_index
    from {{ ref('dim_line_stop') }} as s
    inner join (
        select distinct schedule_version, line, direction_id, stop_id, main_index
        from {{ ref('int_line_trip_stops') }}
        where main_index is not null
    ) as i using (schedule_version, line, direction_id, stop_id)
),

steps as (
    select *, lag(main_index) over (
        partition by schedule_version, line, direction_id order by stop_order
    ) as prev_index
    from main
)

select * from steps where prev_index > main_index
