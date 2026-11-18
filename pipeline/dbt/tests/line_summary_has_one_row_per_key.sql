-- fct_line_summary's key (line, direction_id, time_window) allows a NULL direction_id (both
-- directions), which unique_combination rejects; check uniqueness with NULL as its own value.
select line, direction_id, time_window, count(*) as n
from {{ ref('fct_line_summary') }}
group by line, direction_id, time_window
having count(*) > 1
