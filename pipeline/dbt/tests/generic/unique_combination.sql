-- Grain test: no two rows share these columns. (dbt core's `unique` takes one column, and
-- dbt_utils would add a package download to every build.)
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
