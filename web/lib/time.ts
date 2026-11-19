/**
 * Times for riders, always in Los Angeles whatever the viewer's zone (hard rule 5; web spec
 * section 10). The API sends UTC with a Z.
 */
const ZONE = "America/Los_Angeles";

const clock = new Intl.DateTimeFormat("en-US", {
  timeZone: ZONE,
  hour: "numeric",
  minute: "2-digit",
});
const day = new Intl.DateTimeFormat("en-US", {
  timeZone: ZONE,
  weekday: "short",
  month: "short",
  day: "numeric",
});

/** "2026-12-01T00:52:00Z" → "4:52 PM" (the evening before, in LA). */
export function localTime(iso: string): string {
  return clock.format(new Date(iso));
}

/** "2026-12-01T00:52:00Z" → "Mon, Nov 30". */
export function localDay(iso: string): string {
  return day.format(new Date(iso));
}

/** A GTFS service date ("2026-11-30") as a label. It is a calendar date, not an instant, so it is
 * formatted at noon UTC: a date that no zone shifts to another day. */
export function serviceDay(date: string): string {
  return day.format(new Date(`${date}T12:00:00Z`)).replace(/^\w+, /, "");
}

/** Hour of day 0–23 as a rider reads it: 0 → "12 AM", 17 → "5 PM". */
export function hourLabel(hour: number): string {
  const suffix = hour < 12 ? "AM" : "PM";
  return `${hour % 12 === 0 ? 12 : hour % 12} ${suffix}`;
}

export function minutesSince(iso: string, now: Date): number {
  return Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / 60_000));
}

/** Data older than this shows a notice (web spec section 4). */
export const STALE_AFTER_MINUTES = 60;

/** Older than 60 minutes, to the millisecond. An unreadable timestamp counts as stale: bad data
 * must never read as fresh. */
export function isStale(dataAsOf: string, now: Date): boolean {
  const at = new Date(dataAsOf).getTime();
  return Number.isNaN(at) || now.getTime() - at > STALE_AFTER_MINUTES * 60_000;
}
