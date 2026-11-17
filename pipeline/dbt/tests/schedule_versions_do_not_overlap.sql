-- Every service date is covered by at most one schedule version (pipeline spec, section 4).
-- If two overlapped, every trip on those dates would join twice downstream. Empty ranges
-- (a version superseded the day it took effect) are skipped.
with ranges as (
    select version_id, valid_from, coalesce(valid_to, date '9999-12-31') as valid_to
    from {{ ref('dim_schedule_version') }}
    where valid_to is null or valid_to >= valid_from
)

select a.version_id as a, b.version_id as b
from ranges as a
join ranges as b
    on a.version_id < b.version_id
    and a.valid_from <= b.valid_to
    and b.valid_from <= a.valid_to
