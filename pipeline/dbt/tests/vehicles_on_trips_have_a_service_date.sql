-- A vehicle on a trip must carry the trip's start_date (the day-1 probe found it on every
-- trip). Without it the position can't join its trip, which would then look missed; the
-- schedule-window fallback in spec section 5 isn't built, so fail loudly instead.
select vehicle_id, vehicle_ts, trip_id
from {{ ref('stg_vehicle_positions') }}
where trip_id is not null and service_date is null
