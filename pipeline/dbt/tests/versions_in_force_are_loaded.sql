-- A schedule version that is in force on some date must have its trips and stop times
-- loaded. Otherwise every date it covers would silently schedule zero trips, and nothing
-- could ever look missed (the loader excludes refused versions; this guards the local copy).
select v.version_id
from {{ ref('dim_schedule_version') }} as v
where (v.valid_to is null or v.valid_to >= v.valid_from)
  and (
      not exists (select 1 from {{ ref('dim_trips') }} as t where t.schedule_version = v.version_id)
      or not exists (
          select 1 from {{ ref('dim_stop_times') }} as s where s.schedule_version = v.version_id
      )
  )
