-- One row per threshold that shapes the published numbers: (name). Rendered from the dbt vars
-- of this very build, so the method page (GET /v1/meta/method) can't drift from the values
-- that produced the rates. Values are numbers rendered as text (a non-numeric var fails the
-- build), with a unit; descriptions are rider-readable. The bootstrap's settings are in
-- dim_method_params_nightly, rebuilt with the intervals they describe (ADR-027). A sensitivity
-- run must be a full build, or the page and the numbers come from different vars.
select name, value, unit, description, decision
from (values
    ('window_before_start_min', cast({{ var("window_before_start_min") }} as varchar), 'minutes',
     'How far before the scheduled start the observation window opens, for judging feed health. A bus seen only before its start does not count as running.', 'pipeline spec section 8'),
    ('window_after_end_min', cast({{ var("window_after_end_min") }} as varchar), 'minutes',
     'How late after its scheduled end a trip can still be seen.', 'pipeline spec section 8'),
    ('min_stop_coverage', cast({{ var("min_stop_coverage") }} as varchar), 'share of stops',
     'A seen trip counts as ran if it reached at least this share of its stops; otherwise partial.',
     'ADR-024'),
    ('min_feed_healthy_share', cast({{ var("min_feed_healthy_share") }} as varchar), 'share of 5-minute buckets',
     'A trip not seen is unknown, not missed, if the feeds were healthy for less than this share of its window (or there is no feed data for it).',
     'ADR-024'),
    ('feed_fresh_max_s', cast({{ var("feed_fresh_max_s") }} as varchar), 'seconds',
     'A feed is healthy in a 5-minute period if a fetch succeeded with data less than this old.', 'ADR-024'),
    ('min_cell_trips', cast({{ var("min_cell_trips") }} as varchar), 'trips',
     'Fewest trips behind any published rate.', 'ADR-025, ADR-026'),
    ('min_cell_service_days_weekday', cast({{ var("min_cell_service_days_weekday") }} as varchar), 'service days',
     'Fewest weekdays behind a weekday rate, and fewest service days of any type behind a line or system headline.',
     'ADR-025, ADR-026'),
    ('min_cell_service_days_weekend', cast({{ var("min_cell_service_days_weekend") }} as varchar), 'service days',
     'Fewest Saturdays or Sundays behind a weekend rate.', 'ADR-025'),
    ('min_week_service_days', cast({{ var("min_week_service_days") }} as varchar), 'service days',
     'Fewest service days behind a weekly trend point.', 'ADR-026')
) as t(name, value, unit, description, decision)
