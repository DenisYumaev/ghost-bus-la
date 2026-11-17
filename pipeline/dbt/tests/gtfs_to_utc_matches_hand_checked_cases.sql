-- The SQL conversion agrees with every hand-checked case the Python version is tested against
-- (tests/fixtures/dbt_seeds/gtfs_time_cases.csv): past 24:00, both DST switch days, owl trips
-- on the eve of a switch, a trip spanning midnight UTC. `is distinct from` so a NULL result
-- fails; the last branch fails if the seed didn't load all 16 cases.
with cases as (
    select
        cast(service_date as date) as service_date,
        gtfs_time,
        cast(expected_utc as timestamptz) as expected_utc,
        cast(split_part(gtfs_time, ':', 1) as integer) * 3600
            + cast(split_part(gtfs_time, ':', 2) as integer) * 60
            + cast(split_part(gtfs_time, ':', 3) as integer) as seconds
    from {{ ref('gtfs_time_cases') }}
)

select service_date, gtfs_time, expected_utc, {{ gtfs_to_utc('service_date', 'seconds') }} as got
from cases
where {{ gtfs_to_utc('service_date', 'seconds') }} is distinct from expected_utc
union all
select null, 'seed has fewer than 16 cases', null, null
from (select count(*) as n from cases)
where n < 16
