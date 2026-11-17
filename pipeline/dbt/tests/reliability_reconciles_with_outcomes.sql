-- Every trip with an outcome is counted exactly once in the `all` window (no cell drops or
-- doubles a trip), for scheduled and for each outcome.
with cells as (
    select sum(n_scheduled) as scheduled, sum(n_unknown) as unknown, sum(n_missed) as missed,
           sum(n_ran) as ran, sum(n_partial) as partial
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
)

select * from cells, trips
where cells.scheduled is distinct from trips.scheduled
   or cells.unknown is distinct from trips.unknown
   or cells.missed is distinct from trips.missed
   or cells.ran is distinct from trips.ran
   or cells.partial is distinct from trips.partial
