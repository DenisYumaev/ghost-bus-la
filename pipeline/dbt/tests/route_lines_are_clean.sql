-- Every route has a rider-facing line that isn't empty and has no surrounding whitespace
-- (a route_id like '-13201' would otherwise give line '').
select schedule_version, route_id, line
from {{ ref('dim_routes') }}
where line is null or line = '' or line <> trim(line)
