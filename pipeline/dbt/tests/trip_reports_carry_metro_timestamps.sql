-- Warning: trip reports without Metro's own timestamp. Their report_ts falls back to our fetch
-- time, which ranks them last within a fetch; none were seen on Nov 14-16.
{{ config(severity='warn') }}
select report_ts_source, count(*) as n
from {{ ref('stg_trip_reports') }}
where report_ts_source = 'fetch'
group by 1
