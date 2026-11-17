-- The home page, the trend chart and the line pages count the same trips: in each window the
-- summary's totals equal the sum of the reliability cells, and the weekly trend sums to the `all`
-- window. coalesce: an empty build is fine.
with cells as (
    select time_window, sum(n_scheduled) as scheduled, sum(n_missed) as missed,
           sum(n_missed_unplanned) as unplanned
    from {{ ref('fct_reliability') }}
    group by time_window
),

summary as (
    select s.time_window, s.n_scheduled, s.n_missed, s.n_missed_unplanned,
           coalesce(c.scheduled, 0) as cell_scheduled, coalesce(c.missed, 0) as cell_missed,
           coalesce(c.unplanned, 0) as cell_unplanned
    from {{ ref('fct_system_summary') }} as s
    left join cells as c using (time_window)
),

trend as (
    select coalesce(sum(n_scheduled), 0) as scheduled, coalesce(sum(n_missed), 0) as missed
    from {{ ref('fct_line_trend') }}
)

select 'summary' as check_name, time_window from summary
where n_scheduled <> cell_scheduled or n_missed <> cell_missed or n_missed_unplanned <> cell_unplanned
union all
select 'trend', 'all' from trend, summary
where summary.time_window = 'all'
  and (trend.scheduled <> summary.n_scheduled or trend.missed <> summary.n_missed)
