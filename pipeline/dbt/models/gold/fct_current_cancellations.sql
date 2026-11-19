-- One row per trip still canceled at the newest trip-update fetch in the data: (service_date,
-- trip_id). Feeds serving.cancellation_current and GET /v1/cancellations/current (ADR-029).
-- "Now" is that fetch (as_of, fct_current_cancellations_as_of), not the build clock, so a rebuild
-- of the same data gives the same
-- rows. A trip is listed if the feed announced it canceled (canceled_first_seen_at), hasn't
-- shown it scheduled again since (reinstated_at), and its scheduled end isn't past as_of.
-- Trips come through the crosswalk with their scheduled times (int_trip_observations; hard
-- rule 6). Not filtered by Metro-operated status: this reports what the feed announced.
with as_of as (
    -- The newest fetch the decoded state covers. Not the fetch log: it can list fetches that
    -- haven't been decoded yet (or were missing or quarantined), and would claim coverage the
    -- state doesn't have.
    select as_of from {{ ref('fct_current_cancellations_as_of') }}
)

select
    o.service_date,
    o.trip_id,
    o.schedule_version,
    o.line,
    o.direction_id,
    o.sched_start_utc,
    o.sched_end_utc,
    o.canceled_first_seen_at,
    epoch(o.sched_start_utc) - epoch(o.canceled_first_seen_at) as advance_notice_s,
    a.as_of
from {{ ref('int_trip_observations') }} as o
cross join as_of as a
where o.canceled_first_seen_at is not null
  and o.reinstated_at is null
  and o.sched_end_utc >= a.as_of
