# ADR-023: dbt reads a local, marker-filtered copy of derived data

- **Status:** Accepted
- **Date:** 2026-11-17
- **Supersedes:** pipeline spec section 6's "dbt-duckdb reading Parquet from S3" and "materialize silver and gold as Parquet partitioned by service date" for M1. Publishing to serving (section 13) is unchanged
- **Evidence:** compaction and decode write runs behind `_SUCCESS` markers (PRs #30, #31), and a glob over a day's S3 prefix can see a half-written or superseded run; dbt unit tests can't mock external sources (found building PR #32)

## Context

Since PR #30, every derived dataset (compacted snapshots, decoded tables, extracted schedule versions) is written as a run: new files first, then a `_SUCCESS` marker listing them, then older runs deleted. Readers are correct only if they follow the marker. dbt-duckdb's natural way to read S3 is a glob over a prefix (`read_parquet('s3://…/dt=*/…')`), which ignores markers, and it needs S3 credentials inside DuckDB's `httpfs`.

## Decision

1. `make dbt-sync START= END=` (`ghostbus_decode.sync`) copies, for service dates `START..END`, the marker-listed decoded parts, fetch-log hours, and extracted schedule versions for UTC days `START-1..END+1` into the gitignored `data/`. It is all or nothing: built in `data/.staging/`, swapped in only when complete, and it refuses a range whose UTC days aren't all decoded.
2. dbt builds a DuckDB file in `data/` (`pipeline/dbt/`). Each external source has a thin `src_*` view, so dbt unit tests can mock it.
3. Silver and gold are DuckDB tables for now. Publishing Parquet to S3 arrives with serving (spec section 13) and the M4 scheduler.
4. The end-to-end test (`pipeline/decode/tests/test_dbt.py`) runs `dbt build` over a synthetic world pushed through the real Python steps, offline, with the session in Los Angeles time.

## Why

The marker protocol is what makes rewrites crash-safe, and a reader that ignores it gets mixed days or missing rows without any error. Copying only marker-listed files keeps that guarantee and lets dbt glob the local copy freely. It also keeps S3 credentials out of DuckDB, and repeat builds don't re-download. The cost is a sync step and local disk for the days being built (a day is about 0.7 GB of decoded Parquet), which is fine on a laptop for M1. The full-table rebuild is also simpler than partition overwrite while there are a handful of days. Both are revisited when dbt runs nightly on the VM.

## Alternatives considered

- **dbt reads S3 directly with globs.** Simplest, but ignores markers: during a rewrite it can read a half-written day, or two runs at once, without failing.
- **A dbt macro that reads markers and builds a file list.** Correct and stays on S3, but it puts S3 listing and JSON parsing in Jinja, needs credentials in DuckDB, and is harder to test than a Python function.
- **Write silver and gold as partitioned Parquet now.** Matches the spec's end state, but adds partition-overwrite logic before there's a consumer for those files.

## Consequences

- Readers outside dbt must also follow markers. `compaction_marker`, `decoded_parts`, and `is_extracted` are the helpers.
- `data/` can be deleted at any time; it is rebuilt by `make dbt-sync`.
- `data/ghostbus.duckdb`'s views reference `data/` by relative path, so open it from the repo root.
- Nightly runs on the VM need a bounded sync window and a memory-capped container (hard rule 3), and gold must be published to S3 before anything serves it.

## Would change if

- dbt moves to the VM on a schedule (M4): sync only the open service dates plus late-data reprocessing, and publish gold to S3.
- Local disk or sync time becomes the bottleneck. Then read S3 through a marker-aware list, or materialize silver as partitioned Parquet.
