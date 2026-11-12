# Ghost Bus LA

Reliability lookup and cancellation alerts for LA Metro bus riders.

**Not affiliated with LA Metro.** Data from LA Metro's public realtime API and GTFS schedule.

> **Status:** early build. Nothing is live yet, and this README contains no numbers on purpose: every number it will show must come from a query in this repo.

## The question

An LA Metro rider can see when the next bus is predicted to arrive, but not that their usual trip was canceled until they are standing at the stop, or how reliable their commute actually is.

## What was found

Not yet. Findings will appear here with their method and intervals.

## How it works

An ingest service archives Metro's realtime streams to S3 as raw snapshots. A batch pipeline classifies every scheduled trip, and a separate hot path turns announced cancellations into email alerts. Design: [`docs/SPEC.md`](docs/SPEC.md). Decisions: [`docs/decisions/`](docs/decisions/).

## Run it

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
make install   # dependencies and git hooks
make test      # offline tests, no keys needed
make lint      # ruff, mypy, fixture size check
```

## Limitations

To be written as the method is built. See [`docs/SPEC.md`](docs/SPEC.md) section 2.7.
