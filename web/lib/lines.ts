/** Search and sort for the line list (web spec section 3). */
import type { Schemas } from "@/lib/api/client";

type Line = Schemas["LineListItem"];

export const rateOf = (line: Line): number | null =>
  line.summary.suppressed ? null : (line.summary.missed_rate ?? null);

/** Lines whose slug or name starts with the query ("72" finds 720 and 728), case-insensitive. */
export function matching(lines: Line[], q: string): Line[] {
  const needle = q
    .trim()
    .toLowerCase()
    .replace(/^line\s+/, "");
  if (!needle) return lines;
  return lines.filter(
    (l) => l.line_slug.startsWith(needle) || l.display_name.toLowerCase().startsWith(needle),
  );
}

/** Least reliable first; lines without enough data go last, in line order (never ranked as 0). */
export function byReliability(lines: Line[]): Line[] {
  return lines
    .map((line, index) => ({ line, index, rate: rateOf(line) }))
    .sort((a, b) =>
      a.rate === null || b.rate === null
        ? (a.rate === null ? 1 : 0) - (b.rate === null ? 1 : 0) || a.index - b.index
        : b.rate - a.rate || a.index - b.index,
    )
    .map((x) => x.line);
}
