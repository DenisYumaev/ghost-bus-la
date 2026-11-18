-- Every schedule version that is ever in force has lines, directions and stops. Without this, a
-- version mismatch in the joins would leave the line tables empty and every other test passing.
-- Counted separately per table (joining them would multiply rows).
with versions as (
    select version_id from {{ ref('dim_schedule_version') }} where ever_in_force
),

lines as (select schedule_version, count(*) as n from {{ ref('dim_line') }} group by 1),
directions as (select schedule_version, count(*) as n from {{ ref('dim_line_direction') }} group by 1),
stops as (select schedule_version, count(*) as n from {{ ref('dim_line_stop') }} group by 1)

select v.version_id, l.n as n_lines, d.n as n_directions, s.n as n_stops
from versions as v
left join lines as l on v.version_id = l.schedule_version
left join directions as d on v.version_id = d.schedule_version
left join stops as s on v.version_id = s.schedule_version
where coalesce(l.n, 0) = 0 or coalesce(d.n, 0) = 0 or coalesce(s.n, 0) = 0
