-- One row per realtime feed per 5-minute bucket (pipeline spec, section 6.3): freshness,
-- fetch error rate, healthy flag. The capture SLO (ADR-003) is computed from this.
select
    feed,
    bucket_start,
    n_fetches,
    n_success,
    n_fetches - n_success as n_errors,
    case when n_fetches > 0 then (n_fetches - n_success) / n_fetches end as error_rate,
    freshest_age_s,
    healthy,
    is_padding  -- exclude from the capture SLO
from {{ ref('int_feed_health_5min') }}
