-- Which schedule version is in force on each service date (pipeline spec, section 4).
-- Built in Python (ghostbus_core.schedule_versions); passed through so SQL can join on it.
select * from {{ ref('src_dim_schedule_version') }}
