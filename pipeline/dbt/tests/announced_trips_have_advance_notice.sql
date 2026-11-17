select service_date, trip_id from {{ ref('fct_trip_outcomes') }}
where announced and advance_notice_s is null
