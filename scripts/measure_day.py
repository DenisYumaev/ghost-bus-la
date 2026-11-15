"""Measure one UTC day of the archive from the fetch log (M0: "measure a full day").

    uv run python scripts/measure_day.py --bucket <data bucket> --date 2026-11-14

Reads every `bronze/_fetch_log/dt=<date>/hour=HH/*.jsonl` file (read-only), takes the union of
lines (a mid-hour restart uploads an hour twice, ADR-004), and prints per stream feed:
cuts expected and attempted, outcomes, partial cuts, raw and gzipped bytes stored, and
disconnects. This is the query behind docs/research/measured-day-*.md (hard rule 11).

Credentials: the configured AWS profile (hard rule 9).
"""

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

STREAMS = {"vehicle_positions": 30, "trip_updates": 60}


@dataclass
class FeedDay:
    feed: str
    interval_s: int
    expected: int
    attempted: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    partial: int = 0
    raw_bytes: int = 0
    gz_bytes: int = 0
    disconnects: int = 0

    @property
    def attempted_pct(self) -> float:
        return 100.0 * self.attempted / self.expected


def summarize(lines: set[str], date: str) -> dict[str, FeedDay]:
    """Aggregate fetch-log lines for one UTC date. Pure, so it's tested offline."""
    days = {f: FeedDay(f, i, 86400 // i) for f, i in STREAMS.items()}
    for line in lines:
        rec: dict[str, Any] = json.loads(line)
        day = days.get(rec.get("feed", ""))
        if day is None:
            continue
        stamp = rec.get("fetched_at") or rec.get("at") or ""
        if not stamp.startswith(date):
            continue
        if rec["event"] == "fetch":
            day.attempted += 1
            day.outcomes[rec["outcome"]] += 1
            day.partial += bool(rec.get("partial"))
            if rec["outcome"] == "written":
                day.raw_bytes += rec["bytes"]
                day.gz_bytes += rec["bytes_gz"]
        elif rec["event"] == "disconnect":
            day.disconnects += 1
    return days


def read_lines(s3: Any, bucket: str, date: str) -> set[str]:
    lines: set[str] = set()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"bronze/_fetch_log/dt={date}/"):
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read().decode()
            lines.update(x for x in body.splitlines() if x.strip())
    return lines


def report(days: dict[str, FeedDay]) -> str:
    columns = ["Feed", "Cuts expected", "Attempted", "Outcomes", "Partial", "Raw", "Gzipped"]
    columns.append("Disconnects")
    rows = ["| " + " | ".join(columns) + " |"]
    rows.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for d in days.values():
        outcomes = ", ".join(f"{k} {v}" for k, v in sorted(d.outcomes.items()))
        rows.append(
            f"| {d.feed} ({d.interval_s} s) | {d.expected} | {d.attempted} "
            f"({d.attempted_pct:.2f}%) | {outcomes} | {d.partial} | "
            f"{d.raw_bytes / 1e9:.3f} GB | {d.gz_bytes / 1e6:.1f} MB | {d.disconnects} |"
        )
    total = sum(d.gz_bytes for d in days.values())
    rows.append(f"\nTotal gzipped: {total / 1e9:.3f} GB")
    return "\n".join(rows)


def main() -> None:
    import boto3

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--date", required=True, help="UTC date, YYYY-MM-DD")
    args = parser.parse_args()
    s3 = boto3.client("s3", region_name="us-west-2")
    print(report(summarize(read_lines(s3, args.bucket, args.date), args.date)))


if __name__ == "__main__":
    main()
