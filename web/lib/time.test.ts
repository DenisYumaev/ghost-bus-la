import { describe, expect, it } from "vitest";

import { hourLabel, isStale, localDay, localTime, minutesSince, serviceDay } from "./time";

// vitest.config.ts runs these in Asia/Tokyo: results must still be Los Angeles times.
describe("Los Angeles time, whatever the viewer's zone", () => {
  it("formats a UTC instant as LA clock time", () => {
    expect(new Date().getTimezoneOffset()).toBe(-540); // proves the test really runs in Tokyo
    expect(localTime("2026-12-01T00:52:00Z")).toBe("4:52 PM");
    expect(localDay("2026-12-01T00:52:00Z")).toBe("Mon, Nov 30");
  });

  it("follows daylight saving time", () => {
    expect(localTime("2026-07-01T20:00:00Z")).toBe("1:00 PM"); // PDT, UTC-7
    expect(localTime("2026-12-01T20:00:00Z")).toBe("12:00 PM"); // PST, UTC-8
  });

  it("labels a service date without shifting it a day", () => {
    expect(serviceDay("2026-11-30")).toBe("Nov 30");
    expect(serviceDay("2027-01-01")).toBe("Jan 1");
  });

  it("labels hours the way riders read them", () => {
    expect([0, 1, 11, 12, 13, 23].map(hourLabel)).toEqual([
      "12 AM", "1 AM", "11 AM", "12 PM", "1 PM", "11 PM",
    ]); // prettier-ignore
  });
});

describe("staleness", () => {
  const now = new Date("2026-12-01T18:00:00Z");

  it("counts whole minutes, never negative", () => {
    expect(minutesSince("2026-12-01T17:30:30Z", now)).toBe(29);
    expect(minutesSince("2026-12-01T18:05:00Z", now)).toBe(0);
  });

  it("flags data older than 60 minutes", () => {
    expect(isStale("2026-12-01T17:00:00Z", now)).toBe(false);
    expect(isStale("2026-12-01T16:59:00Z", now)).toBe(true);
    expect(isStale("2026-12-01T16:59:30Z", now)).toBe(true); // 60 min 30 s
    expect(isStale("2026-12-01T17:00:00Z", now)).toBe(false); // exactly 60 min
  });

  it("treats an unreadable timestamp as stale, never fresh", () => {
    expect(isStale("not a time", now)).toBe(true);
  });
});
