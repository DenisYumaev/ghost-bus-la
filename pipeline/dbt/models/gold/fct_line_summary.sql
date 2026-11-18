-- One row per line x direction x window, plus one per line x window for both directions together
-- (direction_id NULL): (line, direction_id, time_window). The line list's headline rate and the
-- line page's summary (API spec GET /v1/lines and /v1/lines/{line}; web line page). Same trips
-- and windows as fct_reliability, pooled over hours and day types, so a line's headline is the
-- sum of its own grid (a dbt test checks it). Suppression (ADR-026): below min_cell_trips trips
-- or min_cell_service_days_weekday service days. Intervals for missed_rate and unplanned_share
-- come with the bootstrap; NULL until then.
with by_direction as (
    select
        o.line,
        o.direction_id,
        w.time_window, w.window_start, w.window_end,
        min(o.service_date) as first_data_date,
        count(distinct o.service_date) filter (where o.outcome <> 'unknown') as n_service_days,
        count(*) as n_scheduled,
        count(*) filter (where o.outcome = 'unknown') as n_unknown,
        count(*) filter (where o.outcome = 'ran') as n_ran,
        count(*) filter (where o.outcome = 'partial') as n_partial,
        count(*) filter (where o.outcome = 'missed') as n_missed,
        count(*) filter (where o.outcome = 'missed' and o.announced) as n_missed_announced,
        count(*) filter (where o.outcome = 'missed' and not o.announced) as n_missed_unplanned,
        count(*) filter (where o.outcome = 'ran' and o.announced) as n_ran_announced
    from {{ ref('int_trip_cells') }} as o
    inner join {{ ref('int_windows') }} as w
        on o.service_date between w.window_start and w.window_end
    group by grouping sets (
        (o.line, o.direction_id, w.time_window, w.window_start, w.window_end),
        (o.line, w.time_window, w.window_start, w.window_end)
    )
),

judged as (
    select
        *,
        n_scheduled - n_unknown as n_trips,
        n_scheduled - n_unknown < {{ var('min_cell_trips') }}
            or n_service_days < {{ var('min_cell_service_days_weekday') }} as suppressed
    from by_direction
)

select
    line,
    direction_id,
    time_window,
    window_start,
    window_end,
    first_data_date,
    n_service_days,
    n_scheduled,
    n_unknown,
    n_trips,
    n_ran,
    n_partial,
    n_missed,
    n_missed_announced,
    n_missed_unplanned,
    n_ran_announced,
    case when not suppressed then n_missed / nullif(n_trips, 0) end as missed_rate,
    case when not suppressed then n_missed_announced / nullif(n_trips, 0) end as announced_rate,
    case when not suppressed then n_missed_unplanned / nullif(n_trips, 0) end as unplanned_rate,
    case when not suppressed and n_missed > 0 then n_missed_unplanned / n_missed end
        as unplanned_share,
    suppressed,
    cast(null as double) as missed_rate_ci_low,
    cast(null as double) as missed_rate_ci_high,
    cast(null as double) as unplanned_share_ci_low,
    cast(null as double) as unplanned_share_ci_high
from judged
