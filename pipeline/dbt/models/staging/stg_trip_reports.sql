-- One row per trip report: (trip_id, service_date, fetched_at, entity_key) (pipeline spec,
-- section 6.1). A report is one GTFS-rt entity about a trip in one fetch; decode wrote one
-- row per stop-time update, so this collapses them back.
--
-- Metro sometimes publishes the same trip twice in one snapshot under different entity IDs
-- (docs/research/duplicate-trip-reports.md: 18,323 of 14.6 million trip-fetches on Nov 14-16;
-- in 227 of the 266 that disagree, the newest report is a cancellation without a vehicle).
-- is_chosen marks one report per trip-fetch: the newest by Metro's timestamp (a report
-- without one ranks last; none so far), then the one with a vehicle, then entity_key, so the
-- choice is total and repeatable. Consumers asking "what did Metro say in this fetch" (state,
-- observed running) must filter on is_chosen: the non-chosen duplicates include stale
-- SCHEDULED reports that still carry a vehicle next to a newer cancellation.
-- report_ts is the entity timestamp, or the fetch time when absent (report_ts_source).
with updates as (
    select * from {{ ref('src_trip_update') }}
),

reports as (
    select
        trip_id,
        start_date as service_date,
        fetched_at,
        coalesce(entity_id, '_noid') as entity_key,
        any_value(feed_ts) as feed_ts,
        any_value(snapshot_sha) as snapshot_sha,
        any_value(route_id) as route_id,
        any_value(direction_id) as direction_id,
        any_value(start_time) as start_time,
        coalesce(any_value(trip_schedule_relationship), 'SCHEDULED') as trip_schedule_relationship,
        any_value(vehicle_id) as vehicle_id,
        any_value(entity_ts) as entity_ts,
        coalesce(any_value(entity_ts), fetched_at) as report_ts,
        case when any_value(entity_ts) is null then 'fetch' else 'entity' end as report_ts_source,
        count(*) filter (where stop_sequence is not null or stop_id is not null) as n_stop_updates
    from updates
    group by trip_id, start_date, fetched_at, coalesce(entity_id, '_noid')
),

ranked as (
    select
        *,
        row_number() over (
            partition by trip_id, service_date, fetched_at
            order by entity_ts desc nulls last, vehicle_id is null, entity_key
        ) as report_rank,
        count(*) over (partition by trip_id, service_date, fetched_at) as n_reports
    from reports
)

select
    trip_id,
    service_date,
    fetched_at,
    entity_key,
    report_rank = 1 as is_chosen,
    n_reports,
    report_ts,
    report_ts_source,
    entity_ts,
    feed_ts,
    snapshot_sha,
    route_id,
    direction_id,
    start_time,
    trip_schedule_relationship,
    vehicle_id,
    n_stop_updates
from ranked
