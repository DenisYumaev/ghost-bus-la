-- Grain test: every row has all key columns, and no two rows share them. (dbt core's
-- `unique` takes one column and ignores NULLs; dbt_utils would add a package download.)
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1 or {% for c in columns %}{{ c }} is null{% if not loop.last %} or {% endif %}{% endfor %}
{% endtest %}
