-- Coverage (spec section 8) is the furthest stop sequence reached over the trip's stop count,
-- which assumes sequences run 1..n. GTFS allows gaps; Metro has none (33,614 trips checked on
-- 2026-11-17). Fail if that changes, rather than report coverage above 1 or skewed.
select schedule_version, trip_id, min(stop_sequence) as first_seq, max(stop_sequence) as last_seq,
       count(*) as n_stops
from {{ ref('dim_stop_times') }}
group by 1, 2
having min(stop_sequence) <> 1 or max(stop_sequence) <> count(*)
