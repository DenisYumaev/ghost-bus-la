/**
 * Numbers for riders (web spec section 1: honest numbers). A rate the API suppressed is null and
 * shows as "not enough data", never as 0%.
 */
export const NOT_ENOUGH_DATA = "not enough data";

/** 0.0472 → "5%". A nonzero rate never reads as 0%: under 1% keeps one decimal ("0.4%"), and
 * under 0.1% shows "<0.1%". The same holds at the top: just under 100% never shows "100%". */
export function percent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return NOT_ENOUGH_DATA;
  const value = rate * 100;
  if (value > 0 && value < 0.1) return "<0.1%";
  if (value > 0 && value < 1) return `${value.toFixed(1)}%`;
  if (value > 99.9 && value < 100) return ">99.9%";
  if (value >= 99 && value < 100) return `${value.toFixed(1)}%`;
  return `${Math.round(value)}%`;
}

/** The 95% interval as "4 to 7%"; null when there's no interval to show. Both ends use the same
 * precision: whole percent, or one decimal when an end is under 1% or 99% and over, or when whole
 * percent would print the same number twice ("4.6 to 5.4%", not "5 to 5%"). An end that isn't 0
 * or 100% never prints as one ("under 0.1", "over 99.9"). */
export function percentRange(
  low: number | null | undefined,
  high: number | null | undefined,
): string | null {
  if (low == null || high == null || !Number.isFinite(low) || !Number.isFinite(high)) return null;
  const [a, b] = [low * 100, high * 100];
  const fine =
    Math.round(a) === Math.round(b) || [a, b].some((v) => (v > 0 && v < 1) || (v >= 99 && v < 100));
  const end = (v: number): string => {
    if (v > 0 && v < 0.1) return "under 0.1";
    if (v > 99.9 && v < 100) return "over 99.9";
    return fine ? v.toFixed(1) : String(Math.round(v));
  };
  return `${end(a)} to ${end(b)}%`;
}

const integer = new Intl.NumberFormat("en-US");

/** 12400 → "12,400". */
export function count(n: number | null | undefined): string {
  return n === null || n === undefined ? "–" : integer.format(n);
}
