select schedule_version, service_id from {{ ref('dim_calendar') }} where start_date > end_date
