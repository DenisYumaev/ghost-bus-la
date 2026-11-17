-- Warning: a trip whose service_id is in neither calendar nor calendar_dates never runs.
{{ config(severity='warn') }}
select t.schedule_version, t.trip_id, t.service_id
from {{ ref('dim_trips') }} as t
where not exists (select 1 from {{ ref('dim_calendar') }} as c
                  where c.schedule_version = t.schedule_version and c.service_id = t.service_id)
  and not exists (select 1 from {{ ref('dim_calendar_dates') }} as d
                  where d.schedule_version = t.schedule_version and d.service_id = t.service_id)
