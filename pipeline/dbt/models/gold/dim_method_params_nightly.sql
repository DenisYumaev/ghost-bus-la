{{ config(tags=['nightly']) }}
-- The bootstrap's settings, rebuilt only with the intervals they describe (tag nightly,
-- ADR-027), so the method page never shows a replicate count the published intervals weren't
-- built with. The seed is listed so a published interval can be reproduced exactly.
select name, value, unit, description, decision
from (values
    ('bootstrap_replicates', cast({{ var("bootstrap_replicates") }} as varchar), 'replicates',
     'Resamples of whole service days behind each 95% interval.', 'ADR-027'),
    ('bootstrap_seed', cast({{ var("bootstrap_seed") }} as varchar), 'seed',
     'Fixes the resampling, so a published interval can be reproduced exactly.', 'ADR-027')
) as t(name, value, unit, description, decision)
