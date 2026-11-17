-- A trip with no stop times would have no scheduled start or end downstream.
select t.schedule_version, t.trip_id
from {{ ref('dim_trips') }} as t
where not exists (
    select 1 from {{ ref('dim_stop_times') }} as s
    where s.schedule_version = t.schedule_version and s.trip_id = t.trip_id
)
