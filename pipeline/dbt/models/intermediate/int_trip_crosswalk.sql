-- One row per realtime trip key: (trip_id, service_date) (pipeline spec, sections 6.2 and 7).
-- Every trip seen in trip updates or vehicle positions, matched to the expanded schedule.
-- v1 is exact: (trip_id, service_date) against the version in force for that date, which
-- int_schedule_expanded already applied (Metro's trip IDs embed a service-change tag, so an
-- ID from another version doesn't match). Fuzzy matching (route, direction, start time) is
-- P1/M4. Unmatched keys stay, counted, so a match-rate drop is visible (tests warn under
-- var('match_rate_alert')).
with seen as (
    select trip_id, service_date, 'trip_updates' as source from {{ ref('stg_trip_reports') }}
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
)

select
    k.trip_id,
    k.service_date,
    k.sources,
    s.schedule_version,
    case when s.trip_id is not null then 'exact' else 'unmatched' end as match_method,
    case when s.trip_id is not null then 1.0 end as match_confidence,
    -- Only dates the schedule covers can match; keys from other dates (the UTC days around
    -- the synced range) aren't evidence of a matching problem.
    k.service_date in (select service_date from {{ ref('int_schedule_expanded') }}) as in_scope
from keys as k
left join scheduled as s
    on s.trip_id = k.trip_id and s.service_date = k.service_date
