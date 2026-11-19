/** Feed capture by day for the status page. */
import type { Schemas } from "@/lib/api/client";
import { localDay } from "@/lib/time";

const parts = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Los_Angeles",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** The Los Angeles calendar date as YYYY-MM-DD, built from parts (locale formats can change). */
export function laDate(iso: string): string {
  const get = (type: string) =>
    parts.formatToParts(new Date(iso)).find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

// The shortest full day (23 hours, spring forward) has 276 five-minute periods. A day with
// fewer for some feed was cut by the 7-day window or the data's edge.
const FULL_DAY_BUCKETS = 23 * 12;

export type DayRow = {
  day: string;
  label: string;
  partial: boolean;
  healthy: Partial<Record<string, number>>;
};

/** Five-minute buckets → the share captured per Los Angeles day and feed, newest day first. */
export function healthByDay(buckets: Schemas["FeedBucket"][]): DayRow[] {
  const days = new Map<string, { label: string; feeds: Map<string, [number, number]> }>();
  for (const b of buckets) {
    const key = laDate(b.bucket_start);
    const day = days.get(key) ?? { label: localDay(b.bucket_start), feeds: new Map() };
    const [healthy, total] = day.feeds.get(b.feed) ?? [0, 0];
    day.feeds.set(b.feed, [healthy + (b.healthy ? 1 : 0), total + 1]);
    days.set(key, day);
  }
  return [...days.entries()]
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([day, { label, feeds }]) => ({
      day,
      label,
      partial: [...feeds.values()].some(([, n]) => n < FULL_DAY_BUCKETS),
      healthy: Object.fromEntries([...feeds].map(([feed, [h, n]]) => [feed, h / n])),
    }));
}
