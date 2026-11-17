-- One row per fetch attempt (pipeline spec, sections 2.5 and 6.1). The hour files are a union:
-- a mid-hour restart uploads an hour twice, repeating its lines, so identical rows collapse
-- (every field is compared, as compaction does). Two *different* attempts with the same feed
-- and time can only come from two ingest processes writing at once; fetch_key's uniqueness
-- test then fails the build on purpose, rather than picking a winner silently.
-- Connection events (connect, disconnect, connect_failed) and uploads are left out here.
with fetches as (
    select distinct
        feed,
        cast(fetched_at as timestamptz) as fetched_at,
        outcome,
        content_hash,
        partial,
        n_entities,
        bytes,
        bytes_gz,
        error,
        connected_s,
        interval_s,
        cast(feed_header_ts as timestamptz) as feed_header_ts,
        ingest_version,
        url_key,
        object_key,
        spool_file,
        n_messages,
        n_unkeyed,
        n_unframed,
        http_status,
        latency_ms
    from {{ ref('src_fetch_log') }}
    where event = 'fetch'
)

select
    -- Explicit UTC: never rely on the session time zone (a laptop session is Los Angeles).
    feed || '@' || strftime(timezone('UTC', fetched_at), '%Y-%m-%dT%H:%M:%S.%f') as fetch_key,
    *
from fetches
