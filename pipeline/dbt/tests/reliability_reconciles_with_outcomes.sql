-- Every trip with an outcome is counted exactly once in the `all` window (no cell drops or
-- doubles a trip), for scheduled and for each outcome. coalesce: an empty build is fine.
with cells as (
    select coalesce(sum(n_scheduled), 0) as scheduled, coalesce(sum(n_unknown), 0) as unknown,
           coalesce(sum(n_missed), 0) as missed, coalesce(sum(n_ran), 0) as ran,
           coalesce(sum(n_partial), 0) as partial
    from {{ ref('fct_reliability') }}
    where time_window = 'all'
),

trips as (
    select count(*) as scheduled,
           count(*) filter (where outcome = 'unknown') as unknown,
           count(*) filter (where outcome = 'missed') as missed,
           count(*) filter (where outcome = 'ran') as ran,
           count(*) filter (where outcome = 'partial') as partial
    from {{ ref('fct_trip_outcomes') }}
    where is_metro_operated is distinct from false
)

select * from cells, trips
where cells.scheduled <> trips.scheduled
   or cells.unknown <> trips.unknown
   or cells.missed <> trips.missed
   or cells.ran <> trips.ran
   or cells.partial <> trips.partial
