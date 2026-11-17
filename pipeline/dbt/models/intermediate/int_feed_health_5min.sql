-- One row per realtime feed per 5-minute bucket: (feed, bucket_start) (pipeline spec, sections
-- 6.2 and 8; ADR-024). Buckets cover every synced UTC day (data/_sync.json start-1..end+1),
-- whether or not anything was fetched, so an outage shows as unhealthy buckets, not as
-- missing rows. Healthy = at least one successful fetch (written or duplicate) whose feed
-- timestamp was under var('feed_fresh_max_s') old when fetched.
with sync as (
    select cast("start" as date) - 1 as first_day, cast("end" as date) + 1 as last_day
    from {{ ref('src_sync_range') }}
),

buckets as (
    select unnest(generate_series(
        timezone('UTC', cast(first_day as timestamp)),
        timezone('UTC', cast(last_day + 1 as timestamp)) - interval 5 minute,
        interval 5 minute
    )) as bucket_start
    from sync
),

feeds as (
    select unnest(['vehicle_positions', 'trip_updates']) as feed
),

fetches as (
    select
        feed,
        time_bucket(interval 5 minute, fetched_at, timezone('UTC', timestamp '2000-01-01'))
            as bucket_start,
        outcome,
        epoch(fetched_at) - epoch(feed_header_ts) as header_age_s
    from {{ ref('stg_fetch_log') }}
    where feed in ('vehicle_positions', 'trip_updates')
),

per_bucket as (
    select
        feed,
        bucket_start,
        count(*) as n_fetches,
        count(*) filter (where outcome in ('written', 'duplicate')) as n_success,
        min(header_age_s) filter (where outcome in ('written', 'duplicate')) as freshest_age_s
    from fetches
    group by feed, bucket_start
)

select
    f.feed,
    b.bucket_start,
    coalesce(p.n_fetches, 0) as n_fetches,
    coalesce(p.n_success, 0) as n_success,
    p.freshest_age_s,
    coalesce(p.freshest_age_s < {{ var('feed_fresh_max_s') }}, false) as healthy
from buckets as b
cross join feeds as f
left join per_bucket as p
    on p.feed = f.feed and p.bucket_start = b.bucket_start
