"""Re-derive one day's scheduled trips from a raw GTFS ZIP, independently of the dbt models.

    uv run python scripts/check_schedule_expansion.py <gtfs.zip> 2026-11-15 [line]

Plain Python over the raw CSVs: calendar weekday and date range, plus calendar_dates
additions, minus removals. Compare with int_schedule_expanded for the same service date and
version. The cross-check behind docs/spec/01-data-pipeline.md section 6.2 (hard rule 11):
Sunday 2026-11-15, version cb1a2283abecc0af, gave 9,534 trips, 12 services, 110 on line 754.
"""

import csv
import datetime
import io
import sys
import zipfile


def main() -> None:
    path, day = sys.argv[1], datetime.date.fromisoformat(sys.argv[2])
    line = sys.argv[3] if len(sys.argv) > 3 else "754"
    with zipfile.ZipFile(path) as z:

        def rows(name: str) -> list[dict[str, str]]:
            return list(csv.DictReader(io.TextIOWrapper(z.open(name), "utf-8-sig")))

        ymd, weekday = day.strftime("%Y%m%d"), day.strftime("%A").lower()
        active = {r["service_id"] for r in rows("calendar.txt")
                  if r[weekday] == "1" and r["start_date"] <= ymd <= r["end_date"]}  # fmt: skip
        for r in rows("calendar_dates.txt"):
            if r["date"] == ymd:
                (active.add if r["exception_type"] == "1" else active.discard)(r["service_id"])
        trips = [t for t in rows("trips.txt") if t["service_id"] in active]
        lines = {r["route_id"]: (r["route_short_name"].strip() or r["route_id"].split("-")[0])
                 for r in rows("routes.txt")}  # fmt: skip
    on_line = sum(1 for t in trips if lines[t["route_id"]] == line)
    print(f"{day}: {len(trips)} trips, {len(active)} services, {on_line} on line {line}")


if __name__ == "__main__":
    main()
