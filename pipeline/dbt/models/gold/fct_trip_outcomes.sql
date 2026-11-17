-- One row per scheduled trip per service date: (service_date, schedule_version, trip_id)
-- (pipeline spec, sections 6.3 and 8; ADR-024). The heart of the project: every other gold
-- table aggregates this one, so every number agrees.
--
-- Decision table, first match wins (rule 4, likely_untracked, comes in M4):
--   1. observed running and coverage >= var('min_stop_coverage')       -> ran
--   2. observed running, coverage below it or unknown (updates only)   -> partial
--   3. not observed and feed-healthy share < var('min_feed_healthy_share') -> unknown
--   5. not observed                                                     -> missed
-- coverage = furthest current_stop_sequence from matched positions / stop count.
-- feed-healthy share = share of 5-minute buckets overlapping the observation window in which
-- both realtime feeds were healthy.
with trips as (
    select * from {{ ref('int_trip_observations') }}
),

health as (
    select bucket_start, bool_and(healthy) as both_healthy
    from {{ ref('int_feed_health_5min') }}
    group by bucket_start
),

shares as (
    select
        t.service_date, t.schedule_version, t.trip_id,
        avg(case when h.both_healthy then 1.0 else 0.0 end) as feed_healthy_share
    from trips as t
    join health as h
        on h.bucket_start < t.window_end
        and h.bucket_start + interval 5 minute > t.window_start
    group by t.service_date, t.schedule_version, t.trip_id
),

classified as (
    select
        t.*,
        coalesce(s.feed_healthy_share, 0.0) as feed_healthy_share,
        t.max_stop_sequence / t.n_stops as stop_coverage
    from trips as t
    left join shares as s using (service_date, schedule_version, trip_id)
)

select
    service_date,
    schedule_version,
    trip_id,
    line,
    route_id,
    direction_id,
    block_id,
    sched_start_utc,
    sched_end_utc,
    case
        when observed_running and stop_coverage >= {{ var('min_stop_coverage') }} then 'ran'
        when observed_running then 'partial'
        when feed_healthy_share < {{ var('min_feed_healthy_share') }} then 'unknown'
        else 'missed'
    end as outcome,
    rt_canceled as announced,
    case when rt_canceled then 'trip_updates' end as announce_source,
    case
        when rt_canceled then epoch(sched_start_utc) - epoch(canceled_first_seen_at)
    end as advance_notice_s,
    stop_coverage,
    feed_healthy_share,
    case when observed_running then 'exact' end as match_method,
    cast(null as boolean) as is_metro_operated,
    n_positions,
    n_updates_with_vehicle
from classified
