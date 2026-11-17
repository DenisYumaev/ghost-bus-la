-- One row per (line, direction_id, day_type, hour_local, time_window): trip counts and rates
-- (pipeline spec, sections 6.3, 8 and 9). Rates follow section 8:
--   missed_rate    = missed / (scheduled - unknown)
--   announced_rate = (missed and announced) / (scheduled - unknown)
--   unplanned_rate = (missed and not announced) / (scheduled - unknown)
-- n_trips is that denominator. partial is counted but never missed. hour_local is the
-- America/Los_Angeles clock hour of the scheduled start, so a 25:30 trip is hour 1 of its own
-- service date (and its day type). Windows end at the last service date with outcomes, never at
-- the build clock, so a rebuild of the same data gives the same table. A cell with fewer than
-- min_cell_trips trips or min_cell_service_days days is suppressed: no rates.
-- ci_low and ci_high come from the cluster bootstrap over service dates (section 9), added in a
-- later PR; NULL until then.
with outcomes as (
    select
        o.line,
        o.direction_id,
        o.service_date,
        d.day_type,
        cast(extract(hour from o.sched_start_utc at time zone 'America/Los_Angeles') as integer)
            as hour_local,
        o.outcome,
        o.announced
    from {{ ref('fct_trip_outcomes') }} as o
    inner join {{ ref('int_service_day_types') }} as d on o.service_date = d.service_date
),

bounds as (
    select min(service_date) as first_day, max(service_date) as last_day from outcomes
),

windows as (
    select '28d' as time_window, cast(last_day - 27 as date) as window_start, last_day as window_end
    from bounds
    union all
    select '90d', cast(last_day - 89 as date), last_day from bounds
    union all
    select 'all', first_day, last_day from bounds
),

cells as (
    select
        o.line,
        o.direction_id,
        o.day_type,
        o.hour_local,
        w.time_window,
        w.window_start,
        w.window_end,
        count(*) as n_scheduled,
        count(*) filter (where o.outcome = 'unknown') as n_unknown,
        count(*) filter (where o.outcome = 'ran') as n_ran,
        count(*) filter (where o.outcome = 'partial') as n_partial,
        count(*) filter (where o.outcome = 'missed') as n_missed,
        count(*) filter (where o.outcome = 'missed' and o.announced) as n_missed_announced,
        count(*) filter (where o.outcome = 'missed' and not o.announced) as n_missed_unplanned,
        count(*) filter (where o.outcome = 'ran' and o.announced) as n_ran_announced,
        count(distinct o.service_date) as n_service_days
    from outcomes as o
    inner join windows as w on o.service_date between w.window_start and w.window_end
    group by all
),

judged as (
    select
        *,
        n_scheduled - n_unknown as n_trips,
        n_scheduled - n_unknown < {{ var('min_cell_trips') }}
            or n_service_days < {{ var('min_cell_service_days') }} as suppressed
    from cells
)

select
    line,
    direction_id,
    day_type,
    hour_local,
    time_window,
    window_start,
    window_end,
    n_scheduled,
    n_unknown,
    n_trips,
    n_ran,
    n_partial,
    n_missed,
    n_missed_announced,
    n_missed_unplanned,
    n_ran_announced,
    n_service_days,
    case when not suppressed then n_missed / n_trips end as missed_rate,
    case when not suppressed then n_missed_announced / n_trips end as announced_rate,
    case when not suppressed then n_missed_unplanned / n_trips end as unplanned_rate,
    -- Share of missed trips that were never announced: the headline (SPEC section 1.3).
    case when not suppressed and n_missed > 0 then n_missed_unplanned / n_missed end
        as unplanned_share,
    suppressed,
    cast(null as double) as ci_low,
    cast(null as double) as ci_high
from judged
