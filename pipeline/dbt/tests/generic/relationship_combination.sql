-- Every row's (columns) exists in `to` as (to_columns): a composite foreign key, for links
-- that only hold within one schedule version, such as (schedule_version, trip_id).
{% test relationship_combination(model, columns, to, to_columns) %}
select {% for c in columns %}child.{{ c }}{% if not loop.last %}, {% endif %}{% endfor %}
from {{ model }} as child
left join {{ to }} as parent
    on {% for c in columns %}child.{{ c }} = parent.{{ to_columns[loop.index0] }}{% if not loop.last %} and {% endif %}{% endfor %}
where parent.{{ to_columns[0] }} is null
{% endtest %}
