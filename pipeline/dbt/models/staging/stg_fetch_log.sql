-- One row per fetch attempt (pipeline spec, sections 2.5 and 6.1). The hour files are a union:
-- a mid-hour restart uploads an hour twice, repeating its lines, so identical rows collapse.
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
        ingest_version
    from {{ ref('src_fetch_log') }}
    where event = 'fetch'
)

select
    -- Explicit UTC: never rely on the session time zone (a laptop session is Los Angeles).
    feed || '@' || strftime(timezone('UTC', fetched_at), '%Y-%m-%dT%H:%M:%S.%f') as fetch_key,
    *
from fetches
