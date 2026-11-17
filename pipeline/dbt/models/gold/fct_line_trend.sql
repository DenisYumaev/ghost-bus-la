-- One row per line x direction x week: (line, direction_id, week_start). Weekly missed,
-- announced and unplanned rates for the trend chart (API spec GET /v1/lines/{line}/trend; web
-- TrendChart). week_start is the Monday of the service date's week; a week has at most 7 service
-- days, so the day minimum doesn't apply, and a week is suppressed only below min_cell_trips
-- trips. n_service_days tells the chart when a week is partial (the first and last weeks of the
-- data, or a gap).
with weeks as (
    select
        line,
        direction_id,
        cast(date_trunc('week', service_date) as date) as week_start,
        count(distinct service_date) filter (where outcome <> 'unknown') as n_service_days,
        count(*) as n_scheduled,
        count(*) filter (where outcome = 'unknown') as n_unknown,
        count(*) filter (where outcome = 'ran') as n_ran,
        count(*) filter (where outcome = 'partial') as n_partial,
        count(*) filter (where outcome = 'missed') as n_missed,
        count(*) filter (where outcome = 'missed' and announced) as n_missed_announced,
        count(*) filter (where outcome = 'missed' and not announced) as n_missed_unplanned
    from {{ ref('int_trip_cells') }}
    group by line, direction_id, cast(date_trunc('week', service_date) as date)
),

judged as (
    select *, n_scheduled - n_unknown as n_trips,
           n_scheduled - n_unknown < {{ var('min_cell_trips') }} as suppressed
    from weeks
)

select
    line,
    direction_id,
    week_start,
    n_service_days,
    n_scheduled,
    n_unknown,
    n_trips,
    n_ran,
    n_partial,
    n_missed,
    n_missed_announced,
    n_missed_unplanned,
    case when not suppressed then n_missed / nullif(n_trips, 0) end as missed_rate,
    case when not suppressed then n_missed_announced / nullif(n_trips, 0) end as announced_rate,
    case when not suppressed then n_missed_unplanned / nullif(n_trips, 0) end as unplanned_rate,
    suppressed
from judged
