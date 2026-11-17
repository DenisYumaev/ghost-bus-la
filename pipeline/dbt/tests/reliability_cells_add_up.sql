-- Within each cell the counts partition the trips, and windows nest (28d within 90d within all).
-- A new outcome value (likely_untracked, M4) would break the first check until it gets a column.
with cells as (select * from {{ ref('fct_reliability') }}),

bad_cells as (
    select line, direction_id, day_type, hour_local, time_window, 'counts do not add up' as problem
    from cells
    where n_scheduled <> n_unknown + n_ran + n_partial + n_missed
       or n_missed <> n_missed_announced + n_missed_unplanned
       or n_trips <> n_scheduled - n_unknown
),

nesting as (
    select a.line, a.direction_id, a.day_type, a.hour_local, a.time_window,
           'window larger than the next wider one' as problem
    from cells as a
    inner join cells as b
        on a.line = b.line and a.direction_id = b.direction_id
        and a.day_type = b.day_type and a.hour_local = b.hour_local
        and ((a.time_window = '28d' and b.time_window = '90d')
             or (a.time_window = '90d' and b.time_window = 'all'))
    where a.n_scheduled > b.n_scheduled or a.n_missed > b.n_missed
)

select * from bad_cells
union all
select * from nesting
