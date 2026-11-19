-- Bootstrap weights on real data: each window has bootstrap_replicates replicates; within each
-- day-type stratum a replicate draws exactly as many dates as the stratum has; every date of the
-- window is drawn at least once across replicates, about once per replicate on average
-- (R +- 5 sqrt(R) in total).
with dates as (
    select w.time_window, o.service_date, any_value(o.day_type) as day_type
    from {{ ref('int_trip_cells') }} as o
    inner join {{ ref('int_windows') }} as w
        on o.service_date between w.window_start and w.window_end
    where o.outcome <> 'unknown'
    group by w.time_window, o.service_date
),

stratum_sizes as (
    select time_window, day_type, count(*) as n_dates from dates group by time_window, day_type
),

drawn as (
    select b.time_window, d.day_type, b.replicate, sum(b.weight) as n_drawn
    from {{ ref('int_bootstrap_weights') }} as b
    inner join dates as d on b.time_window = d.time_window and b.service_date = d.service_date
    group by b.time_window, d.day_type, b.replicate
),

per_date as (
    select d.time_window, d.service_date, coalesce(sum(b.weight), 0) as total
    from dates as d
    left join {{ ref('int_bootstrap_weights') }} as b
        on d.time_window = b.time_window and d.service_date = b.service_date
    group by d.time_window, d.service_date
)

select 'replicate count or stratum draws' as problem, s.time_window, s.day_type as detail
from stratum_sizes as s
left join drawn as r on s.time_window = r.time_window and s.day_type = r.day_type
group by s.time_window, s.day_type, s.n_dates
having count(r.replicate) <> {{ var('bootstrap_replicates') }}
    or min(r.n_drawn) <> s.n_dates or max(r.n_drawn) <> s.n_dates
union all
select 'date draws off', time_window, cast(service_date as varchar) from per_date
where abs(total - {{ var('bootstrap_replicates') }}) > 5 * sqrt({{ var('bootstrap_replicates') }})
