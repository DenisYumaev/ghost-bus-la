{{ config(tags=['nightly']) }}
-- One row per window x replicate x service date drawn: (time_window, replicate, service_date),
-- with how many times that date was drawn (pipeline spec section 9; ADR-027). The cluster
-- bootstrap resamples whole service dates, because trips on one day share causes. It resamples
-- within day-type strata: a window's weekdays, Saturdays and Sundays are each redrawn with
-- replacement, as many as the window has, so every replicate keeps the calendar's real mix (20
-- weekdays and 4 Saturdays in a 28-day window) and no weekend cell is left without days. Only
-- dates with a trip in the denominator count (unknown-only days are feed outages, not clusters).
-- Draws are reproducible (macro bootstrap_draw), so a rebuild gives the same intervals.
with dates as (
    select w.time_window, o.service_date, any_value(o.day_type) as day_type
    from {{ ref('int_trip_cells') }} as o
    inner join {{ ref('int_windows') }} as w
        on o.service_date between w.window_start and w.window_end
    where o.outcome <> 'unknown'
    group by w.time_window, o.service_date
),

numbered as (
    select
        time_window,
        day_type,
        service_date,
        row_number() over (partition by time_window, day_type order by service_date) - 1
            as date_index,
        count(*) over (partition by time_window, day_type) as n_dates
    from dates
),

strata as (
    select distinct time_window, day_type, n_dates from numbered
),

draws as (
    select
        s.time_window,
        s.day_type,
        r.replicate,
        {{ bootstrap_draw('s.time_window', 's.day_type', 'r.replicate', 'k.draw', 's.n_dates') }}
            as date_index
    from strata as s
    cross join range(1, {{ var('bootstrap_replicates') }} + 1) as r(replicate)
    cross join lateral (select unnest(range(s.n_dates)) as draw) as k
)

select d.time_window, d.replicate, n.service_date, count(*) as weight
from draws as d
inner join numbered as n
    on d.time_window = n.time_window and d.day_type = n.day_type and d.date_index = n.date_index
group by d.time_window, d.replicate, n.service_date
