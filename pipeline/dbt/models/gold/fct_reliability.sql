-- One row per (line, direction_id, day_type, hour_local, time_window): trip counts and rates
-- (pipeline spec, sections 6.3, 8 and 9). Rates follow section 8:
--   missed_rate    = missed / (scheduled - unknown)
--   announced_rate = (missed and announced) / (scheduled - unknown)
--   unplanned_rate = (missed and not announced) / (scheduled - unknown)
-- n_trips is that denominator. partial is counted but never missed. Day type, hour and the
-- Metro-operated scope come from int_trip_cells; the windows from int_windows (ADR-025).
-- A cell with fewer than min_cell_trips trips, or fewer service days (days with at least one trip
-- in the denominator) than min_cell_service_days_weekday (weekday cells) or
-- min_cell_service_days_weekend (Saturday and Sunday cells; ADR-025), is suppressed: no rates.
-- first_data_date is the first service date with data in the window, which can be later than
-- window_start early on or after a gap.
-- ci_low and ci_high: the 95% cluster-bootstrap interval for missed_rate only (section 9;
-- ADR-026, ADR-027), published only where the rate is and is above 0. The interval tables are
-- nightly (tag nightly); a frequent build without them reads the last night's intervals.
with cells as (
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
        count(distinct o.service_date) filter (where o.outcome <> 'unknown') as n_service_days,
        min(o.service_date) as first_data_date
    from {{ ref('int_trip_cells') }} as o
    inner join {{ ref('int_windows') }} as w
        on o.service_date between w.window_start and w.window_end
    group by all
),

judged as (
    select
        *,
        n_scheduled - n_unknown as n_trips,
        n_scheduled - n_unknown < {{ var('min_cell_trips') }}
            or n_service_days < case day_type
                when 'weekday' then {{ var('min_cell_service_days_weekday') }}
                else {{ var('min_cell_service_days_weekend') }}
            end as suppressed
    from cells
)

select
    j.line,
    j.direction_id,
    j.day_type,
    j.hour_local,
    j.time_window,
    j.window_start,
    j.window_end,
    j.first_data_date,
    j.n_scheduled,
    j.n_unknown,
    j.n_trips,
    j.n_ran,
    j.n_partial,
    j.n_missed,
    j.n_missed_announced,
    j.n_missed_unplanned,
    j.n_ran_announced,
    j.n_service_days,
    case when not j.suppressed then j.n_missed / nullif(j.n_trips, 0) end as missed_rate,
    case when not j.suppressed then j.n_missed_announced / nullif(j.n_trips, 0) end as announced_rate,
    case when not j.suppressed then j.n_missed_unplanned / nullif(j.n_trips, 0) end as unplanned_rate,
    -- Share of missed trips that were never announced: the headline (SPEC section 1.3).
    case when not j.suppressed and j.n_missed > 0 then j.n_missed_unplanned / j.n_missed end
        as unplanned_share,
    j.suppressed,
    -- No interval for a rate of 0: every replicate agrees, and the bootstrap can't bound it.
    case when not j.suppressed and j.n_missed > 0 then b.missed_rate_ci_low end as ci_low,
    case when not j.suppressed and j.n_missed > 0 then b.missed_rate_ci_high end as ci_high
from judged as j
left join {{ ref('int_bootstrap_intervals') }} as b
    on b.grain = 'cell'
    and j.time_window = b.time_window and j.line = b.line
    and j.direction_id is not distinct from b.direction_id
    and j.day_type = b.day_type and j.hour_local = b.hour_local
