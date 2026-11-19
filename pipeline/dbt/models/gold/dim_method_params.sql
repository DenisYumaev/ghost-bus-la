-- One row per threshold that shapes the published numbers: (name). Rendered from the dbt vars
-- of this very build, so the method page (GET /v1/meta/method) can't drift from the values
-- that produced the rates. Values are text with a unit; descriptions are rider-readable.
select name, value, unit, description, decision
from (values
    ('window_before_start_min', '{{ var("window_before_start_min") }}', 'minutes',
     'How early before its scheduled start a trip can be seen running.', 'pipeline spec section 8'),
    ('window_after_end_min', '{{ var("window_after_end_min") }}', 'minutes',
     'How late after its scheduled end a trip can still be seen.', 'pipeline spec section 8'),
    ('min_stop_coverage', '{{ var("min_stop_coverage") }}', 'share of stops',
     'A seen trip counts as ran if it reached at least this share of its stops; otherwise partial.',
     'ADR-024'),
    ('min_feed_healthy_share', '{{ var("min_feed_healthy_share") }}', 'share of 5-minute buckets',
     'A trip not seen is unknown, not missed, if the feeds were healthy for less than this share of its window.',
     'ADR-024'),
    ('feed_fresh_max_s', '{{ var("feed_fresh_max_s") }}', 'seconds',
     'A feed is healthy in a 5-minute period if it delivered data at most this old.', 'ADR-024'),
    ('min_cell_trips', '{{ var("min_cell_trips") }}', 'trips',
     'Fewest trips behind any published rate.', 'ADR-025, ADR-026'),
    ('min_cell_service_days_weekday', '{{ var("min_cell_service_days_weekday") }}', 'service days',
     'Fewest weekdays behind a weekday rate, and behind any line or system headline.',
     'ADR-025, ADR-026'),
    ('min_cell_service_days_weekend', '{{ var("min_cell_service_days_weekend") }}', 'service days',
     'Fewest Saturdays or Sundays behind a weekend rate.', 'ADR-025'),
    ('min_week_service_days', '{{ var("min_week_service_days") }}', 'service days',
     'Fewest service days behind a weekly trend point.', 'ADR-026'),
    ('bootstrap_replicates', '{{ var("bootstrap_replicates") }}', 'replicates',
     'Resamples of whole service days behind each 95% interval.', 'ADR-027')
) as t(name, value, unit, description, decision)
