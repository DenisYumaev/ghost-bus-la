{#
  The UTC instant of a GTFS time (seconds since noon minus 12 h) on a service date
  (pipeline spec, section 5): local noon on the service date in Los Angeles, as an instant,
  minus 12 real hours, plus the seconds. Same rule as ghostbus_core.service_date.to_utc;
  tests/fixtures/gtfs_time_cases.csv pins both to the same hand-checked values
  (tests/gtfs_to_utc_matches_hand_checked_cases.sql).
#}
{% macro gtfs_to_utc(service_date, seconds) -%}
    (timezone('America/Los_Angeles', cast({{ service_date }} as timestamp) + interval 12 hour)
     - interval 12 hour + {{ seconds }} * interval 1 second)
{%- endmacro %}
