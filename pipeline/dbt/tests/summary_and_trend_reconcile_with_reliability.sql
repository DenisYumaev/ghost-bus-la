-- The home page, the line pages, the trend chart and the reliability grid count the same trips.
-- Full joins with coalesce, so a missing window or an empty table on either side is a failure,
-- never a skipped comparison:
-- * per window, fct_system_summary = sum of fct_reliability cells;
-- * per line x direction x window, fct_line_summary = sum of that line's cells;
-- * per line x window, the both-directions row = the sum of its direction rows;
-- * the weekly trend sums to the `all` window.
with cells as (
    select time_window, line, direction_id, sum(n_scheduled) as scheduled,
           sum(n_unknown) as unknown, sum(n_ran) as ran, sum(n_partial) as partial,
           sum(n_missed) as missed, sum(n_missed_unplanned) as unplanned
    from {{ ref('fct_reliability') }}
    group by time_window, line, direction_id
),

window_cells as (
    select time_window, sum(scheduled) as scheduled, sum(unknown) as unknown, sum(ran) as ran,
           sum(partial) as partial, sum(missed) as missed, sum(unplanned) as unplanned
    from cells group by time_window
),

summary_check as (
    select 'summary vs cells' as check_name, coalesce(s.time_window, c.time_window) as time_window
    from {{ ref('fct_system_summary') }} as s
    full join window_cells as c on s.time_window = c.time_window
    where coalesce(s.n_scheduled, 0) <> coalesce(c.scheduled, 0)
       or coalesce(s.n_unknown, 0) <> coalesce(c.unknown, 0)
       or coalesce(s.n_ran, 0) <> coalesce(c.ran, 0)
       or coalesce(s.n_partial, 0) <> coalesce(c.partial, 0)
       or coalesce(s.n_missed, 0) <> coalesce(c.missed, 0)
       or coalesce(s.n_missed_unplanned, 0) <> coalesce(c.unplanned, 0)
),

line_direction_check as (
    select 'line summary vs cells', coalesce(l.time_window, c.time_window)
    from (select * from {{ ref('fct_line_summary') }} where direction_id is not null) as l
    full join cells as c
        on l.time_window = c.time_window and l.line = c.line and l.direction_id = c.direction_id
    where coalesce(l.n_scheduled, 0) <> coalesce(c.scheduled, 0)
       or coalesce(l.n_missed, 0) <> coalesce(c.missed, 0)
       or coalesce(l.n_missed_unplanned, 0) <> coalesce(c.unplanned, 0)
),

line_both_check as (
    select 'both directions vs directions', coalesce(b.time_window, d.time_window)
    from (select * from {{ ref('fct_line_summary') }} where direction_id is null) as b
    full join (
        select time_window, line, sum(n_scheduled) as scheduled, sum(n_missed) as missed
        from {{ ref('fct_line_summary') }}
        where direction_id is not null
        group by time_window, line
    ) as d on b.time_window = d.time_window and b.line = d.line
    where coalesce(b.n_scheduled, 0) <> coalesce(d.scheduled, 0)
       or coalesce(b.n_missed, 0) <> coalesce(d.missed, 0)
),

trend_check as (
    select 'trend vs all', 'all'
    from (
        select coalesce(sum(n_scheduled), 0) as scheduled, coalesce(sum(n_missed), 0) as missed,
               coalesce(sum(n_missed_unplanned), 0) as unplanned
        from {{ ref('fct_line_trend') }}
    ) as t
    left join (
        select * from {{ ref('fct_system_summary') }} where time_window = 'all'
    ) as s on true
    where t.scheduled <> coalesce(s.n_scheduled, 0)
       or t.missed <> coalesce(s.n_missed, 0)
       or t.unplanned <> coalesce(s.n_missed_unplanned, 0)
)

select * from summary_check
union all select * from line_direction_check
union all select * from line_both_check
union all select * from trend_check
