-- One row per line x direction x window, plus one per line x window for both directions together
-- (direction_id NULL): (line, direction_id, time_window). The line list's headline rate and the
-- line page's summary (API spec GET /v1/lines and /v1/lines/{line}; web line page). Same trips
-- and windows as fct_reliability, pooled over hours and day types, so a line's headline is the
-- sum of its own grid (a dbt test checks it). Suppression (ADR-026): below min_cell_trips trips
-- or min_cell_service_days_weekday service days. Intervals for missed_rate and unplanned_share
-- come from the cluster bootstrap (ADR-027), published only where the rate is.
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
    j.line,
    j.direction_id,
    j.time_window,
    j.window_start,
    j.window_end,
    j.first_data_date,
    j.n_service_days,
    j.n_scheduled,
    j.n_unknown,
    j.n_trips,
    j.n_ran,
    j.n_partial,
    j.n_missed,
    j.n_missed_announced,
    j.n_missed_unplanned,
    j.n_ran_announced,
    case when not j.suppressed then j.n_missed / nullif(j.n_trips, 0) end as missed_rate,
    case when not j.suppressed then j.n_missed_announced / nullif(j.n_trips, 0) end as announced_rate,
    case when not j.suppressed then j.n_missed_unplanned / nullif(j.n_trips, 0) end as unplanned_rate,
    case when not j.suppressed and j.n_missed > 0 then j.n_missed_unplanned / j.n_missed end
        as unplanned_share,
    j.suppressed,
    -- No interval for a rate of 0 or a share of 0 or 1: every replicate agrees there, and a
    -- percentile bootstrap would claim a certainty the data can't give (ADR-027).
    case when not j.suppressed and j.n_missed > 0 then b.missed_rate_ci_low end
        as missed_rate_ci_low,
    case when not j.suppressed and j.n_missed > 0 then b.missed_rate_ci_high end
        as missed_rate_ci_high,
    case when not j.suppressed and j.n_missed_unplanned between 1 and j.n_missed - 1
        then b.unplanned_share_ci_low end as unplanned_share_ci_low,
    case when not j.suppressed and j.n_missed_unplanned between 1 and j.n_missed - 1
        then b.unplanned_share_ci_high end as unplanned_share_ci_high
from judged as j
left join {{ ref('int_bootstrap_intervals') }} as b
    on b.grain = case when j.direction_id is null then 'line' else 'line_direction' end
    and j.time_window = b.time_window and j.line = b.line
    and j.direction_id is not distinct from b.direction_id
