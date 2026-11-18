-- One row per grain x window x replicate x key: the bootstrap replicate's re-weighted counts
-- (pipeline spec section 9; ADR-027). Grains:
--   cell            line x direction x day type x hour (fct_reliability)
--   line_direction  line x direction                   (fct_line_summary)
--   line            line, both directions               (fct_line_summary, direction_id NULL)
--   system          everything                          (fct_system_summary)
-- Each replicate re-weights every cell's daily counts by how often its date was drawn, so all
-- grains come from the same resampled days in one pass. A replicate that drew none of a cell's
-- dates has no row for it. Materialized on its own so the aggregation can spill to disk; the
-- percentiles are taken in int_bootstrap_intervals.
with cell_days as (
    select
        w.time_window,
        o.service_date,
        o.line,
        o.direction_id,
        o.day_type,
        o.hour_local,
        count(*) filter (where o.outcome <> 'unknown') as n_trips,
        count(*) filter (where o.outcome = 'missed') as n_missed,
        count(*) filter (where o.outcome = 'missed' and not o.announced) as n_unplanned
    from {{ ref('int_trip_cells') }} as o
    inner join {{ ref('int_windows') }} as w
        on o.service_date between w.window_start and w.window_end
    group by all
),

replicates as (
    select
        case
            when grouping(c.line) = 1 then 'system'
            when grouping(c.direction_id) = 1 then 'line'
            when grouping(c.day_type) = 1 then 'line_direction'
            else 'cell'
        end as grain,
        c.time_window,
        b.replicate,
        c.line,
        c.direction_id,
        c.day_type,
        c.hour_local,
        sum(b.weight * c.n_trips) as n_trips,
        sum(b.weight * c.n_missed) as n_missed,
        sum(b.weight * c.n_unplanned) as n_unplanned
    from cell_days as c
    inner join {{ ref('int_bootstrap_weights') }} as b
        on c.time_window = b.time_window and c.service_date = b.service_date
    group by grouping sets (
        (c.time_window, b.replicate, c.line, c.direction_id, c.day_type, c.hour_local),
        (c.time_window, b.replicate, c.line, c.direction_id),
        (c.time_window, b.replicate, c.line),
        (c.time_window, b.replicate)
    )
)


select * from replicates
