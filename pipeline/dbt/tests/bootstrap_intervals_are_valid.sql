-- One interval row per grain and key (NULL keys compared as values), grains as documented, and
-- every bound a proportion with low <= high.
select 'duplicate key' as problem, grain, time_window
from {{ ref('int_bootstrap_intervals') }}
group by grain, time_window, line, direction_id, day_type, hour_local
having count(*) > 1
union all
select 'bad grain', grain, time_window from {{ ref('int_bootstrap_intervals') }}
where grain not in ('cell', 'line_direction', 'line', 'system') or grain is null
union all
select 'bad bounds', grain, time_window from {{ ref('int_bootstrap_intervals') }}
where not (missed_rate_ci_low between 0 and 1 and missed_rate_ci_high between 0 and 1
           and missed_rate_ci_low <= missed_rate_ci_high)
   or (unplanned_share_ci_low is not null
       and not (unplanned_share_ci_low between 0 and 1 and unplanned_share_ci_high between 0 and 1
                and unplanned_share_ci_low <= unplanned_share_ci_high))
