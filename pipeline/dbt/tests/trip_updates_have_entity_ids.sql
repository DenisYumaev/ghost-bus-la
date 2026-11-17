-- GTFS-rt requires an entity id, and stg_trip_reports keys reports on it: two frames without
-- one would collapse into a single report and mix their fields.
select trip_id, start_date, fetched_at
from {{ ref('src_trip_update') }}
where entity_id is null
limit 10
