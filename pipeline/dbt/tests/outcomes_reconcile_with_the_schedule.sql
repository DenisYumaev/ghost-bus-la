-- The reconciliation identity (pipeline spec, section 10): for every service date, scheduled
-- trips = sum of outcomes (ran + partial + likely_untracked + missed + unknown; ADR-024: no
-- likely_untracked in M1). Nothing dropped, nothing double counted.
select coalesce(e.service_date, o.service_date) as service_date, e.scheduled, o.outcomes
from (select service_date, count(*) as scheduled from {{ ref('int_schedule_expanded') }} group by 1) as e
full join (
    select service_date,
           count(*) filter (where outcome in ('ran', 'partial', 'missed', 'unknown')) as outcomes
    from {{ ref('fct_trip_outcomes') }}
    group by 1
) as o using (service_date)
where e.scheduled is distinct from o.outcomes
