-- One row per realtime trip key: (trip_id, service_date) (pipeline spec, sections 6.2 and 7;
-- ADR-001 decision 4). Every trip seen in trip updates or vehicle positions, mapped to a
-- scheduled trip. The key omits schedule_version because each service date has exactly one
-- version in force (int_service_dates); the matched version is a column.
--
-- v1 is exact: (trip_id, service_date) against the version in force, which
-- int_schedule_expanded already applied (Metro's trip IDs embed a service-change tag, so an ID
-- from another version doesn't match). scheduled_trip_id is what consumers join on, so fuzzy
-- matching (P1/M4) can map a realtime ID to a different scheduled trip without changing them.
-- Unmatched keys stay, counted. in_scope = the service date is in the synced range, whether
-- or not it schedules anything, so a version that failed to load shows as unmatched keys
-- (tests: match rate per feed, warn under var('match_rate_alert'), error under 0.80).
with seen as (
    select trip_id, service_date, 'trip_updates' as source
    from {{ ref('stg_trip_reports') }}
    where trip_id is not null
    union
    select trip_id, service_date, 'vehicle_positions' as source
    from {{ ref('stg_vehicle_positions') }}
    where trip_id is not null
),

keys as (
    select trip_id, service_date, list(distinct source order by source) as sources
    from seen
    group by trip_id, service_date
),

scheduled as (
    select service_date, schedule_version, trip_id from {{ ref('int_schedule_expanded') }}
),

synced_dates as (
    select service_date from {{ ref('int_service_dates') }}
)

select
    k.trip_id,
    k.service_date,
    k.sources,
    s.schedule_version,
    s.trip_id as scheduled_trip_id,
    case when s.trip_id is not null then 'exact' else 'unmatched' end as match_method,
    case when s.trip_id is not null then 1.0 end as match_confidence,
    coalesce(k.service_date in (select service_date from synced_dates), false) as in_scope
from keys as k
left join scheduled as s
    on s.trip_id = k.trip_id and s.service_date = k.service_date
