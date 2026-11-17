-- int_trip_observations has exactly the trips int_schedule_expanded has: nothing dropped by
-- a join, nothing duplicated (the base of the reconciliation identity, spec section 10).
select coalesce(e.service_date, o.service_date) as service_date, e.n as scheduled, o.n as observed
from (select service_date, count(*) as n from {{ ref('int_schedule_expanded') }} group by 1) as e
full join (select service_date, count(*) as n from {{ ref('int_trip_observations') }} group by 1) as o
    using (service_date)
where e.n is distinct from o.n
