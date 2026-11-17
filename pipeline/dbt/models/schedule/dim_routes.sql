-- One row per route per schedule version. `line` is the rider-facing name and is text:
-- Metro has '10/48' and 'Dodger Stadium Express' (pipeline spec, section 4).
-- The G Line (route_id 901-13201) and J Line (910-13201) have no route_short_name; their line
-- is the number before the service-change tag, which is also how Metro numbers them in
-- route_long_name ('Metro G Line (Orange) 901'). Found by the not-null test on real data.
select
    schedule_version,
    route_id,
    coalesce(nullif(trim(route_short_name), ''), split_part(route_id, '-', 1)) as line,
    route_long_name,
    route_desc,
    route_type,
    route_color,
    route_text_color
from {{ ref('src_gtfs_routes') }}
