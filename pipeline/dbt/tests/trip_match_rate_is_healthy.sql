-- Warning: the share of in-scope realtime trip keys that matched the schedule exactly is
-- below var('match_rate_alert') (pipeline spec, section 7). A sudden drop usually means a
-- new schedule version wasn't loaded.
{{ config(severity='warn') }}
select service_date,
       count(*) filter (where match_method = 'exact') / count(*) as match_rate
from {{ ref('int_trip_crosswalk') }}
where in_scope
group by service_date
having count(*) filter (where match_method = 'exact') / count(*) < {{ var('match_rate_alert') }}
