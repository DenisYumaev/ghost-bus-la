-- One row per trip x service date ever marked CANCELED: (trip_id, service_date)
-- (pipeline spec, sections 6.1 and 8).
--
-- Built from every report, not only the chosen one, and ordered by Metro's report time
-- (report_ts), not fetch time: canceled entries linger in the feed for hours (day-1 probe),
-- so a stale CANCELED report fetched late must not outrank a newer SCHEDULED one.
--
-- - first_ever_canceled_at: the first fetch with any CANCELED report.
-- - first_seen_at: the first fetch of the *final* cancellation episode, i.e. CANCELED
--   reports newer than the last SCHEDULED report before the newest cancellation. For
--   canceled -> scheduled -> canceled, advance notice runs from the second cancellation:
--   the first was retracted, and riders weren't told again until then.
-- - reinstated_at: report time of the first SCHEDULED report newer than the newest CANCELED
--   one; NULL if none. Whether that counts as a withdrawal depends on the trip's scheduled
--   start (alerts spec: only while the start is still ahead), which needs the schedule, so
--   int_trip_observations applies that cutoff.
with reports as (
    select * from {{ ref('stg_trip_reports') }}
),

canceled_trips as (
    select
        trip_id,
        service_date,
        max(report_ts) as last_canceled_report_ts,
        min(fetched_at) as first_ever_canceled_at,
        max(fetched_at) as last_seen_at,
        count(distinct fetched_at) as n_snapshots,
        any_value(route_id) as route_id,
        any_value(direction_id) as direction_id,
        any_value(start_time) as start_time
    from reports
    where trip_schedule_relationship = 'CANCELED'
    group by trip_id, service_date
),

scheduled as (
    select r.trip_id, r.service_date, r.report_ts
    from reports as r
    join canceled_trips as c using (trip_id, service_date)
    where r.trip_schedule_relationship = 'SCHEDULED'
),

bounds as (
    select
        c.trip_id,
        c.service_date,
        max(s.report_ts) filter (where s.report_ts < c.last_canceled_report_ts)
            as scheduled_before_last_cancel,
        min(s.report_ts) filter (where s.report_ts > c.last_canceled_report_ts)
            as reinstated_at
    from canceled_trips as c
    left join scheduled as s using (trip_id, service_date)
    group by c.trip_id, c.service_date
),

final_episode as (
    select r.trip_id, r.service_date, min(r.fetched_at) as first_seen_at
    from reports as r
    join bounds as b using (trip_id, service_date)
    where r.trip_schedule_relationship = 'CANCELED'
      and (b.scheduled_before_last_cancel is null or r.report_ts > b.scheduled_before_last_cancel)
    group by r.trip_id, r.service_date
)

select
    c.trip_id,
    c.service_date,
    c.route_id,
    c.direction_id,
    c.start_time,
    f.first_seen_at,
    c.first_ever_canceled_at,
    c.last_seen_at,
    c.last_canceled_report_ts,
    c.n_snapshots,
    b.reinstated_at,
    b.reinstated_at is not null as reinstated
from canceled_trips as c
join bounds as b using (trip_id, service_date)
join final_episode as f using (trip_id, service_date)
