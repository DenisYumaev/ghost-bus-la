-- stop_order runs 1..n within each line x direction, with no gaps (stop pickers rely on it).
select line, direction_id, count(*) as n, max(stop_order) as max_order
from {{ ref('dim_line_stop') }}
group by line, direction_id
having max(stop_order) <> count(*) or min(stop_order) <> 1
