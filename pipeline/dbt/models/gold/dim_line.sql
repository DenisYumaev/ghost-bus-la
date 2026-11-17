-- One row per line per schedule version that is ever in force: (schedule_version, line). Feeds
-- serving.line (API spec, section 7); the API serves the version in force on the rider's date.
-- line_kind is Metro's route_long_name ("Metro Rapid Line"); description its route_desc
-- ("HOLLYWOOD - ATHENS VIA VERMONT AV", upper case as published). display_name is what riders
-- call the line: the number for buses, "G Line" for "Metro G Line (Orange) 901" (the busway
-- lines have no route_short_name). line_number is the leading number for a natural sort ('2'
-- before '10/48'; named services like 'Dodger Stadium Express' have none and sort last).
-- Routes with no trips in a version (Metro lists a few) are left out. is_metro_operated is NULL
-- until the contracted-lines seed (ADR-024 decision 6).
select
    r.schedule_version,
    r.line,
    coalesce(
        nullif(regexp_extract(r.route_long_name, '^Metro ([A-Z]) Line', 1), '') || ' Line',
        r.line
    ) as display_name,
    try_cast(nullif(regexp_extract(r.line, '^([0-9]+)', 1), '') as integer) as line_number,
    r.route_id,
    r.route_long_name as line_kind,
    r.route_desc as description,
    r.route_type,
    r.route_color,
    r.route_text_color,
    cast(null as boolean) as is_metro_operated
from {{ ref('dim_routes') }} as r
inner join {{ ref('dim_schedule_version') }} as v
    on r.schedule_version = v.version_id and v.ever_in_force
where exists (
    select 1 from {{ ref('dim_trips') }} as t
    where t.schedule_version = r.schedule_version and t.route_id = r.route_id
)
