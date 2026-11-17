-- GTFS requires times at a trip's first and last stop; without them the trip has no
-- scheduled start or end. Refuse rather than borrow a neighbouring stop's time.
-- (None in Metro's 2026-11-15 version.)
with bounds as (
    select schedule_version, trip_id, min(stop_sequence) as first_seq, max(stop_sequence) as last_seq
    from {{ ref('dim_stop_times') }}
    group by 1, 2
)

select st.schedule_version, st.trip_id, st.stop_sequence
from {{ ref('dim_stop_times') }} as st
join bounds as b using (schedule_version, trip_id)
where st.stop_sequence in (b.first_seq, b.last_seq)
  and st.arrival_s is null and st.departure_s is null
