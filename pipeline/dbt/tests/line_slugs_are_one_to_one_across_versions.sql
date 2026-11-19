-- A URL slug names one line, and a line keeps one slug, across every schedule version: a slug
-- in a bookmarked URL must never come to mean a different line (ADR-028).
select 'slug used by two lines' as problem, line_slug as value
from {{ ref('dim_line') }}
group by line_slug
having count(distinct line) > 1
union all
select 'line with two slugs', line
from {{ ref('dim_line') }}
group by line
having count(distinct line_slug) > 1
union all
select 'empty slug', line from {{ ref('dim_line') }} where coalesce(line_slug, '') = ''
