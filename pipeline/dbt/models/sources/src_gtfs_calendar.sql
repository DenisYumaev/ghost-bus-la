-- Thin view over the external gtfs.calendar files, so models (and dbt unit tests, which can't
-- mock an external source) build on a relation dbt can inspect.
{{ config(materialized='view') }}
select * from {{ source('gtfs', 'calendar') }}
