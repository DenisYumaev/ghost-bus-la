-- Warning: a service date in the synced range has no schedule version in force, so it
-- schedules nothing and can't have outcomes. Expected before 2026-11-15 (the archive's first
-- ZIP); anywhere later it means a new ZIP wasn't loaded (make gtfs-load).
{{ config(severity='warn') }}
select service_date from {{ ref('int_service_dates') }} where schedule_version is null
