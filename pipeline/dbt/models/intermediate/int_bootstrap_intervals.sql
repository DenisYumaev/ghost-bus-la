{{ config(tags=['nightly']) }}
-- One row per grain x window x key: 95% percentile intervals from the cluster bootstrap over
-- service dates (pipeline spec section 9; ADR-026, ADR-027). Percentiles are found by ranking
-- the replicates (a sort, which spills to disk at scale) and interpolating between the two
-- nearest ranks, the same definition as quantile_cont: position p * (n - 1) from 0. Replicates
-- with no trips for a key don't count (n_replicates says how many did); unplanned_share uses only
-- replicates with at least one missed trip (n_share_replicates), so it is conditional on misses.
with rates as (
    select grain, time_window, line, direction_id, day_type, hour_local,
           'missed_rate' as metric, n_missed / n_trips as value
    from {{ ref('int_bootstrap_replicates') }}
    where n_trips > 0
    union all
    select grain, time_window, line, direction_id, day_type, hour_local,
           'unplanned_share', n_unplanned / n_missed
    from {{ ref('int_bootstrap_replicates') }}
    where n_missed > 0
),

ranked as (
    select
        *,
        row_number() over keyed - 1 as rank0,
        count(*) over (partition by grain, time_window, line, direction_id, day_type, hour_local,
                       metric) as n
    from rates
    window keyed as (
        partition by grain, time_window, line, direction_id, day_type, hour_local, metric
        order by value
    )
),

bounds as (
    select
        grain, time_window, line, direction_id, day_type, hour_local, metric, n,
        -- quantile_cont: value at position p * (n - 1), interpolated.
        sum(value * case
            when rank0 = floor(0.025 * (n - 1)) and rank0 = ceil(0.025 * (n - 1)) then 1.0
            when rank0 = floor(0.025 * (n - 1)) then ceil(0.025 * (n - 1)) - 0.025 * (n - 1)
            when rank0 = ceil(0.025 * (n - 1)) then 0.025 * (n - 1) - floor(0.025 * (n - 1))
            else 0 end) as ci_low,
        sum(value * case
            when rank0 = floor(0.975 * (n - 1)) and rank0 = ceil(0.975 * (n - 1)) then 1.0
            when rank0 = floor(0.975 * (n - 1)) then ceil(0.975 * (n - 1)) - 0.975 * (n - 1)
            when rank0 = ceil(0.975 * (n - 1)) then 0.975 * (n - 1) - floor(0.975 * (n - 1))
            else 0 end) as ci_high
    from ranked
    where rank0 in (floor(0.025 * (n - 1)), ceil(0.025 * (n - 1)),
                    floor(0.975 * (n - 1)), ceil(0.975 * (n - 1)))
    group by grain, time_window, line, direction_id, day_type, hour_local, metric, n
)

select
    grain,
    time_window,
    line,
    direction_id,
    day_type,
    hour_local,
    max(n) filter (where metric = 'missed_rate') as n_replicates,
    max(n) filter (where metric = 'unplanned_share') as n_share_replicates,
    max(ci_low) filter (where metric = 'missed_rate') as missed_rate_ci_low,
    max(ci_high) filter (where metric = 'missed_rate') as missed_rate_ci_high,
    max(ci_low) filter (where metric = 'unplanned_share') as unplanned_share_ci_low,
    max(ci_high) filter (where metric = 'unplanned_share') as unplanned_share_ci_high
from bounds
group by grain, time_window, line, direction_id, day_type, hour_local
