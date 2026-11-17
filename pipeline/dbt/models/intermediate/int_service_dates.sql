-- One row per service date in scope: (service_date) (pipeline spec, sections 4 and 6.2).
-- In scope = the range make dbt-sync copied completely (data/_sync.json); the UTC days around
-- it are synced too, but their service dates are only partly covered. Each date gets the
-- schedule version in force: the one whose valid_from..valid_to contains it (versions never
-- overlap: tests/schedule_versions_do_not_overlap.sql). A date with no version in force (before
-- the archive's first ZIP, 2026-11-15) gets none and is reported by a warning test.
with sync as (
    select cast("start" as date) as first_day, cast("end" as date) as last_day
    from {{ ref('src_sync_range') }}
),

days as (
    select cast(unnest(generate_series(first_day, last_day, interval 1 day)) as date) as service_date
    from sync
),

versions as (
    select version_id, valid_from, valid_to
    from {{ ref('dim_schedule_version') }}
    where valid_to is null or valid_to >= valid_from
)

select
    d.service_date,
    v.version_id as schedule_version,
    isodow(d.service_date) as iso_dow
from days as d
left join versions as v
    on d.service_date >= v.valid_from
    and (v.valid_to is null or d.service_date <= v.valid_to)
