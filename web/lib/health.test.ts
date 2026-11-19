import { describe, expect, it } from "vitest";

import { healthByDay, laDate } from "./health";

const bucket = (feed: string, at: string, healthy: boolean) => ({
  feed, bucket_start: at, n_fetches: 10, n_success: healthy ? 10 : 0, n_errors: healthy ? 0 : 10,
  error_rate: healthy ? 0 : 1, freshest_age_s: 3, healthy,
}); // prettier-ignore

/** Every five-minute bucket from `from` (inclusive) to `to` (exclusive), for one feed. */
function day(feed: string, from: string, to: string): ReturnType<typeof bucket>[] {
  const out = [];
  for (let t = Date.parse(from); t < Date.parse(to); t += 300_000) {
    out.push(bucket(feed, new Date(t).toISOString(), true));
  }
  return out;
}

describe("laDate", () => {
  it("is the Los Angeles calendar date", () => {
    expect(laDate("2026-12-02T07:55:00Z")).toBe("2026-12-01");
    expect(laDate("2026-12-02T08:00:00Z")).toBe("2026-12-02");
  });
});

describe("healthByDay", () => {
  it("groups buckets by Los Angeles day, newest first, with the share captured per feed", () => {
    const rows = healthByDay([
      // 07:55 UTC on Dec 2 is still Dec 1 in Los Angeles.
      bucket("trip_updates", "2026-12-02T07:55:00Z", true),
      bucket("trip_updates", "2026-12-01T20:00:00Z", false),
      bucket("vehicle_positions", "2026-12-01T20:00:00Z", true),
      bucket("trip_updates", "2026-12-02T08:00:00Z", true),
    ]);
    expect(rows.map((r) => [r.day, r.label])).toEqual([
      ["2026-12-02", "Wed, Dec 2"],
      ["2026-12-01", "Tue, Dec 1"],
    ]);
    expect(rows[1]?.healthy).toEqual({ trip_updates: 0.5, vehicle_positions: 1 });
  });

  it("marks a day cut short as partial, and a full day, even a 23-hour one, as complete", () => {
    const rows = healthByDay([
      // Nov 2, 2026 in LA: a normal 24-hour day (PST all day).
      ...day("trip_updates", "2026-11-02T08:00:00Z", "2026-11-03T08:00:00Z"),
      // Mar 8, 2026: spring forward, 23 hours (08:00 UTC to 07:00 UTC next day).
      ...day("trip_updates", "2026-03-08T08:00:00Z", "2026-03-09T07:00:00Z"),
      // Nov 3: only the first six hours are in the window.
      ...day("trip_updates", "2026-11-03T08:00:00Z", "2026-11-03T14:00:00Z"),
    ]);
    expect(rows.map((r) => [r.day, r.partial])).toEqual([
      ["2026-11-03", true],
      ["2026-11-02", false],
      ["2026-03-08", false],
    ]);
  });
});
