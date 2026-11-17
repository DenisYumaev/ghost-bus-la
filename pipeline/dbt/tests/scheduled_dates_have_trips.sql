-- Every service date in scope that has a schedule version in force schedules at least one
-- trip. Zero trips means the version's calendar has run out (Metro's current one ends
-- 2026-12-12) or its tables weren't synced (extracted by an older extractor): outcomes for
-- that date would silently be empty, so fail.
select d.service_date, d.schedule_version
from {{ ref('int_service_dates') }} as d
where d.schedule_version is not null
  and not exists (
      select 1 from {{ ref('int_schedule_expanded') }} as e where e.service_date = d.service_date
  )
