# ADR-027: The cluster bootstrap runs as DuckDB SQL inside dbt, nightly, stratified by day type

- **Status:** Accepted
- **Date:** 2026-11-18
- **Supersedes:** pipeline spec section 9's "Runs nightly in Python (`analysis/bootstrap.py`)". The method is still a cluster bootstrap over service dates, with 2,000 replicates, a fixed seed and a 95% percentile interval. Two refinements are added: resampling within day-type strata, and no interval at 0 or 1.
- **Evidence** (all from `scripts/bench_bootstrap.py` unless noted; laptop, DuckDB 2.0.0, 2 threads, 3 GB DuckDB memory limit, file-backed so DuckDB can spill):
  - numpy is not on the stack list and not installed. A pure-Python loop over cells × replicates × days would take hours.
  - `90 2000`: 858,060 trips (Nov 15's real trips copied onto 90 dates).
    - Weights: 0.1 s.
    - Replicate sums: 74.8 million rows in 62–68 s (three runs).
    - Percentiles: 20–24 s.
    - About 83–90 s in total.
    - Peak process memory: 4.2 GB, measured with `/usr/bin/time -l`. That is about 1.2 GB above the DuckDB limit.
  - `5 2000 --check`: the ranked percentiles match DuckDB's `quantile_cont` on all 25,236 keys, maximum difference 1.1 × 10⁻¹⁶. A single-query `quantile_cont` version runs out of memory at 3 GB from about 14 days, because it holds every value and can't spill.
  - Draw quality, checked in a DuckDB session. With `hash(seed, window, r, k) % n` and n = 16, 32 or 64, every one of 2,000 replicates drew exactly the same number of distinct dates (11, 19, 38; standard deviation 0). DuckDB's multi-argument hash XORs its last argument in without a final mix, so for a power-of-two n each replicate is the same pattern relabelled. Wrapping it, `hash(hash(...)) % n`, gives the expected mean (10.31 against 10.30 at n = 16) with spread. Found by the SQL review of this PR.
  - Real data (one service date): replicate sums 5.2 s, percentiles 1.5 s. With two service dates (one Sunday, one weekday) the full build takes 27 s.

## Context

Section 9 asks for intervals from a cluster bootstrap: resample whole service dates with replacement, because trips on one day share causes. ADR-026 extends the intervals to the line and system summaries. The spec placed the bootstrap in a separate nightly Python job that writes columns back into dbt's tables. That would need a second engine, a write path into the warehouse, and numpy.

## Decision

1. **Three dbt models, tagged `nightly`.**
   - `int_bootstrap_weights`: each replicate's draws of service dates.
   - `int_bootstrap_replicates`: re-weighted counts for every grain in one pass, with grouping sets (cell, line × direction, line, system).
   - `int_bootstrap_intervals`: 95% percentiles.

   The 10-minute open-date build runs `dbt build --exclude tag:nightly`. The gold tables then join the interval table the last nightly build left, so intervals can be up to a day old, while the rates are current.
2. **Stratified by day type.** Within each window, a replicate redraws the weekdays, the Saturdays and the Sundays separately, each with replacement, as many as the stratum has. Every replicate keeps the calendar's real mix (20 weekdays, 4 Saturdays, 4 Sundays in 28 days). So no weekend cell loses replicates, and the summaries' intervals aren't widened by a weekday/weekend mix that varies between replicates. Only dates with a trip in the denominator are clusters; unknown-only days are outages.
3. **Reproducible draws** through the macro `bootstrap_draw`: `hash(hash(seed, window, stratum, r, k)) % n`. The seed and the replicate count are dbt vars. A test checks the draw function for 13 stratum sizes, including powers of two: mean distinct dates within 5%, spread present, every index drawn R ± 5√R times.
4. **Spill-friendly percentiles.** The replicate sums are their own table. Percentiles come from ranking and interpolating between the two nearest ranks, the same definition as `quantile_cont`.
5. **What gets published.** An interval appears only where its rate does. None is published for a missed rate of 0, or for an unplanned share of 0 or 1: every replicate agrees there, and a percentile interval would claim a certainty the data can't give. A replicate that drew none of a key's dates doesn't count toward it (`n_replicates`). The share uses only replicates with a missed trip (`n_share_replicates`), so it is conditional on misses occurring.
6. **Names.**
   - `fct_reliability`'s `ci_low` and `ci_high` are the `missed_rate` interval only.
   - The summaries carry `missed_rate_ci_*` and `unplanned_share_ci_*`.
   - Other rates carry no interval (ADR-026; API spec section 1).

## Why

- **One engine, one build.** Every number and its interval come from the same trips in the same dbt project. There is no second job writing back into the warehouse.
- **Determinism.** Hash-based draws make a rebuild identical without storing random state. The Asia/Kolkata build in the tests confirms nothing depends on the session.
- **Stratifying matches how the data was collected.** The calendar fixes how many Saturdays a window has, so the bootstrap shouldn't treat that as random.
- **Nightly is enough.** Intervals change slowly, while the 10-minute build has a 90 s budget, and the bootstrap alone takes about 90 s at 90 days.

## Alternatives considered

- **A Python job with numpy:** a new dependency (stack rule) and a second engine writing into dbt's output.
- **A pure-Python bootstrap:** no dependency, but about 500 million multiply-adds for 90 days.
- **An analytic cluster-robust (delta method) interval:** cheap, but section 9 chose the bootstrap, and the delta method is poor near 0 with few days, exactly the thin weekend cells.
- **Unstratified date resampling (the first draft):** a 28-day window's Saturday count would vary from 0 to 8 between replicates. About 1.3% of replicates would have none, and the summaries would be widened by the varying mix.
- **One query with `quantile_cont`:** runs out of memory at 3 GB.

## Consequences

- Until a stratum has more than one date, every interval in it has width 0. The day minimums (ADR-025, ADR-026) keep those rates, and so their intervals, unpublished.
- `int_bootstrap_replicates` is the largest table in the warehouse, about 75 million rows at 90 days. The `all` window grows with history.
- DuckDB's `hash` is stable within a version. An upgrade may change the draws, and so the intervals. Pin the version, and expect interval changes in the PR that upgrades it.
- **VERIFY before the pipeline is scheduled on the VM (M4; pipeline spec section 11):**
  - measure the nightly build's peak memory on the t4g.medium;
  - run it in a container with its own memory cap, so the OOM killer can never pick ingest (hard rule 3);
  - set `GHOSTBUS_DBT_MEMORY` well below that cap, allowing for the measured ~1.2 GB overshoot.

## Would change if

- The VM can't fit the nightly bootstrap: lower the memory limit and let it spill, cap `all` at a year, or use fewer replicates for `all`.
- The `all` window's cost passes the nightly budget as history grows. Section 11's alert fires at twice the budget.
