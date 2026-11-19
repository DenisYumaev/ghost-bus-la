{{ config(severity='warn') }}
-- A URL slug names one line in every schedule version synced (ADR-028), so a bookmarked URL
-- doesn't come to mean a different line. A warning, not an error: a collision with an old
-- version only threatens old links, and must not stop publishing. Within one version a
-- collision would make slug -> line ambiguous, so that is an error (unique_combination on
-- dim_line). The slug is a function of line, so one line always has one slug.
select line_slug, count(distinct line) as n_lines
from {{ ref('dim_line') }}
group by line_slug
having count(distinct line) > 1
