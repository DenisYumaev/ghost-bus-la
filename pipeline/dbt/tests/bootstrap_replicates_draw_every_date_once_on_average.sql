-- Every replicate draws exactly as many service dates as its window has (with replacement), and
-- there are bootstrap_replicates replicates per window.
with dates as (
    select time_window, count(distinct service_date) as n_dates
    from {{ ref('int_trip_cells') }} as o
    inner join {{ ref('int_windows') }} as w
        on o.service_date between w.window_start and w.window_end
    group by time_window
),

draws as (
    select time_window, replicate, sum(weight) as n_drawn
    from {{ ref('int_bootstrap_weights') }}
    group by time_window, replicate
)

select d.time_window, d.n_dates, count(r.replicate) as n_replicates,
       min(r.n_drawn) as min_drawn, max(r.n_drawn) as max_drawn
from dates as d
left join draws as r on d.time_window = r.time_window
group by d.time_window, d.n_dates
having count(r.replicate) <> {{ var('bootstrap_replicates') }}
    or min(r.n_drawn) <> d.n_dates or max(r.n_drawn) <> d.n_dates
