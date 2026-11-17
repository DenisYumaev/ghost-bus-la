-- Thin view over data/_sync.json: which service dates the local copy is complete for.
{{ config(materialized='view') }}
select * from {{ source('sync', 'sync_range') }}
