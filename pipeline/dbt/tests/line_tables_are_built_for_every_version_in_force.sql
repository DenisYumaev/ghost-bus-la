-- Every schedule version that is ever in force has lines, directions and stops. Without this, a
-- version mismatch in the joins would leave the line tables empty and every other test passing.
select v.version_id, count(distinct l.line) as n_lines, count(distinct d.line) as n_dir_lines,
       count(distinct s.line) as n_stop_lines
from {{ ref('dim_schedule_version') }} as v
left join {{ ref('dim_line') }} as l on v.version_id = l.schedule_version
left join {{ ref('dim_line_direction') }} as d on v.version_id = d.schedule_version
left join {{ ref('dim_line_stop') }} as s on v.version_id = s.schedule_version
where v.ever_in_force
group by v.version_id
having count(distinct l.line) = 0 or count(distinct d.line) = 0 or count(distinct s.line) = 0
