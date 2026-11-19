-- One row: the newest trip-update fetch the decoded state covers (ADR-029). Published on its own
-- so the API can say how current an empty cancellation list is: "nothing canceled as of 4:52 PM"
-- versus no data at all. tests/current_cancellations_have_a_fetch_to_be_current_as_of.sql fails
-- the build if there is none.
select max(fetched_at) as as_of from {{ ref('stg_trip_reports') }}
