-- A line whose name is all punctuation would get an empty slug and no URL (ADR-028).
select schedule_version, line from {{ ref('dim_line') }} where coalesce(line_slug, '') = ''
