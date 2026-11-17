-- One row per reporting window: (time_window). Windows end at the last service date with
-- outcomes, never at the build clock, so rebuilding the same data gives the same tables (ADR-025):
-- 28d and 90d are that date and the 27 or 89 before it; all starts at the first date with data.
with bounds as (
    select min(service_date) as first_day, max(service_date) as last_day
    from {{ ref('int_trip_cells') }}
)

select '28d' as time_window, cast(last_day - 27 as date) as window_start, last_day as window_end
from bounds
union all
select '90d', cast(last_day - 89 as date), last_day from bounds
union all
select 'all', first_day, last_day from bounds
