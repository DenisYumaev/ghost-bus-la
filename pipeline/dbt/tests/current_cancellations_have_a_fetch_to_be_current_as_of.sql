-- Without a decoded trip-update fetch, the current-cancellation list would publish empty and
-- look like "nothing canceled" (ADR-029): fail the build instead.
select * from {{ ref('fct_current_cancellations_as_of') }} where as_of is null
