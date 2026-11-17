-- Warning: the open-ended (newest) schedule version's calendar ends within a week. With no
-- new ZIP after that, dates schedule nothing and nothing fails. Metro's current schedule
-- ends 2026-12-12; the next is expected for Dec 13 (pipeline spec, section 4).
{{ config(severity='warn') }}
with newest as (
    select version_id from {{ ref('dim_schedule_version') }} where valid_to is null
),

calendar_end as (
    select schedule_version, max(end_date) as last_day from {{ ref('dim_calendar') }} group by 1
    union all
    select schedule_version, max(service_date) from {{ ref('dim_calendar_dates') }} group by 1
)

select n.version_id, max(c.last_day) as last_day
from newest as n
join calendar_end as c on c.schedule_version = n.version_id
group by n.version_id
having max(c.last_day) < current_date + 7
