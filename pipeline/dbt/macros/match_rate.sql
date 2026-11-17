{#
  Per feed and service date, the share of in-scope realtime trip keys that matched the
  schedule (pipeline spec, sections 7 and 10), keeping rows under `threshold`. Per feed, so a
  vehicle-position matching failure isn't diluted by trip updates.
#}
{% macro match_rate_below(threshold) %}
with per_source as (
    select service_date, unnest(sources) as source, match_method
    from {{ ref('int_trip_crosswalk') }}
    where in_scope
)

select service_date, source,
       count(*) filter (where match_method <> 'unmatched') / count(*) as match_rate
from per_source
group by service_date, source
having count(*) filter (where match_method <> 'unmatched') / count(*) < {{ threshold }}
{% endmacro %}
