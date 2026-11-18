-- One row per window x replicate x service date drawn: (time_window, replicate, service_date),
-- with how many times that date was drawn (pipeline spec section 9; ADR-027). The cluster
-- bootstrap resamples whole service dates, because trips on one day share causes: each replicate
-- draws as many dates as the window has, with replacement. Draws are reproducible: the date
-- index for draw k of replicate r is hash(seed, window, r, k) mod n_dates, so a rebuild of the
-- same data gives the same intervals (drill 3). Dates never drawn in a replicate have no row.
with dates as (
    select w.time_window, o.service_date
    from {{ ref('int_trip_cells') }} as o
    inner join {{ ref('int_windows') }} as w
        on o.service_date between w.window_start and w.window_end
    group by w.time_window, o.service_date
),

numbered as (
    select
        time_window,
        service_date,
        row_number() over (partition by time_window order by service_date) - 1 as date_index,
        count(*) over (partition by time_window) as n_dates
    from dates
),

windows as (
    select distinct time_window, n_dates from numbered
),

draws as (
    select
        w.time_window,
        r.replicate,
        hash({{ var('bootstrap_seed') }}, w.time_window, r.replicate, k.draw) % w.n_dates
            as date_index
    from windows as w
    cross join range(1, {{ var('bootstrap_replicates') }} + 1) as r(replicate)
    cross join lateral (select unnest(range(w.n_dates)) as draw) as k
)

select d.time_window, d.replicate, n.service_date, count(*) as weight
from draws as d
inner join numbered as n on d.time_window = n.time_window and d.date_index = n.date_index
group by d.time_window, d.replicate, n.service_date
