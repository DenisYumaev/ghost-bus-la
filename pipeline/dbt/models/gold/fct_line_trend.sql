-- One row per line x direction x week: (line, direction_id, week_start). Weekly missed,
-- announced and unplanned rates for the trend chart (API spec GET /v1/lines/{line}/trend; web
-- TrendChart). week_start is the Monday of the service date's week. A week is suppressed below
-- min_cell_trips trips or min_week_service_days service days (ADR-026): trips on one day share
-- causes, so a week with only a day or two of data (the newest week, a gap) would turn one bad
-- day into a spike. n_service_days lets the chart mark partial weeks. Weeks with no trips have
-- no row; the API anchors "the last N weeks" on the newest week_start of all lines and fills
-- gaps as empty points (API spec section 4.1). Trend points carry no intervals (ADR-026).
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
           n_scheduled - n_unknown < {{ var('min_cell_trips') }}
               or n_service_days < {{ var('min_week_service_days') }} as suppressed
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
