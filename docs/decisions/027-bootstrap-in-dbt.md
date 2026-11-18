# ADR-027: The cluster bootstrap runs as DuckDB SQL inside dbt, not as a Python job

- **Status:** Accepted
- **Date:** 2026-11-18
- **Supersedes:** pipeline spec section 9's "Runs nightly in Python (`analysis/bootstrap.py`)". The method itself is unchanged: cluster bootstrap over service dates, 2,000 replicates, fixed seed, 95% percentile interval.
- **Evidence:**
  - numpy is not on the stack list and not installed; a pure-Python loop over cells × replicates × days would take hours.
  - Benchmark (`scripts/bench_bootstrap.py 90 2000 <scratch>`; laptop, DuckDB 2.0.0, 2 threads, 3 GB DuckDB memory limit): Nov 15's 9,534 real trips copied onto 90 dates (858,060 trips), 2,000 replicates.
    - Weights: 0.1 s.
    - Replicate sums: 74.6 million rows in 67–68 s (two runs).
    - Percentiles: 22–24 s.
    - Peak process memory: 4.2 GB.
  - A single-query version with DuckDB's `quantile_cont` ran out of memory at 3 GB. It holds every replicate value in memory and doesn't spill.
  - On real data (one service date): the replicate sums take 5.2 s and the percentiles 1.5 s.

## Context

Section 9 asks for intervals from a cluster bootstrap: resample whole service dates with replacement, because trips on one day share causes. ADR-026 extends the intervals to the line and system summaries. The spec placed the bootstrap in a separate nightly Python job that writes columns into dbt's tables. That would need a second engine, a write path back into the warehouse, and numpy.

## Decision

1. **Three dbt models.**
   - `int_bootstrap_weights`: each replicate's draws of service dates, per window.
   - `int_bootstrap_replicates`: each replicate's re-weighted counts, for every grain in one pass with grouping sets (cell, line × direction, line, system).
   - `int_bootstrap_intervals`: 95% percentiles.

   The gold tables join the intervals and publish them only where the rate itself is published.
2. **Reproducible draws, no random state.** Draw k of replicate r in a window picks date index `hash(seed, window, r, k) mod n_dates`. The seed and replicate count are dbt vars (`bootstrap_seed`, `bootstrap_replicates`).
3. **Spill-friendly percentiles.**
   - The replicate sums are their own table, so the aggregation can spill to disk.
   - Percentiles are found by ranking and interpolating between the two nearest ranks, the same definition as `quantile_cont`. A sort spills to disk; `quantile_cont` doesn't.
   - Checked against `quantile_cont` on the benchmark: 366 keys, maximum difference 6 × 10⁻¹⁶.
4. **Edge cases.**
   - A replicate that draws none of a cell's dates has no trips for it and doesn't count toward that cell's percentiles (`n_replicates` reports how many did).
   - `unplanned_share` uses replicates with at least one missed trip.

## Why

- **One engine, one build.** Every number and its interval come from the same `dbt build`, from the same trips. A Python job writing back would need ordering, locking and a second test harness.
- **Determinism.** Hash-based draws make a rebuild bit-for-bit identical (drill 3's property) without storing random state. The Asia/Kolkata test build confirms nothing depends on the session.
- **Cost.** A 90-day warehouse adds about 90 seconds on a laptop, inside the nightly budget.

## Alternatives considered

- **A Python job with numpy:** a new dependency (stack rule) and a second engine writing into dbt's output.
- **A pure-Python bootstrap:** no dependency, but about 500 million multiply-adds for 90 days; too slow.
- **An analytic cluster-robust (delta method) interval in SQL:** cheap, but section 9 chose the bootstrap, and the delta method behaves badly for rates near 0 with few clusters, which is exactly the thin weekend cells.
- **One query with `quantile_cont`:** simpler, but out of memory at 3 GB on 90 days.

## Consequences

- With one service date every interval has width 0: resampling one day always gives that day. The day minimums (ADR-025, ADR-026) keep rates, and so intervals, unpublished until there is variation to measure.
- `int_bootstrap_replicates` is the largest table in the warehouse, about 75 million rows at 90 days. The `all` window grows with history, so its cost grows linearly.
- DuckDB's `hash` is stable within a version. A DuckDB upgrade may change the draws, and so the intervals, slightly. Pin the version, and expect interval changes in the PR that upgrades it.

## Would change if

- The pipeline on the VM (t4g.medium, 4 GB) can't fit the replicate step. The benchmark's 4.2 GB peak was on a laptop with a 3 GB DuckDB limit, so this must be measured on the VM at deploy (M2). Options then: lower the memory limit and let it spill, cap the `all` window at a year, or use fewer replicates for `all`.
- The `all` window's cost passes the nightly budget as history grows.
