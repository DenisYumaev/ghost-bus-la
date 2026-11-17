-- One row per line in the schedule version in force on the last synced service date: (line).
-- Feeds serving.line (API spec, section 7). `line_kind` is Metro's route_long_name ("Metro Rapid
-- Line"); `description` its route_desc ("HOLLYWOOD - ATHENS VIA VERMONT AV").
-- is_metro_operated is NULL until the contracted-lines seed (ADR-024 decision 6).
with current_version as (
    select schedule_version
    from {{ ref('int_service_dates') }}
    qualify row_number() over (order by service_date desc) = 1
)

select
    r.line,
    r.route_id,
    r.route_long_name as line_kind,
    r.route_desc as description,
    r.route_type,
    r.route_color,
    r.route_text_color,
    cast(null as boolean) as is_metro_operated,
    r.schedule_version
from {{ ref('dim_routes') }} as r
inner join current_version as v on r.schedule_version = v.schedule_version
