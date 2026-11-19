/**
 * Hour × day-type grid of the share of trips that never ran (web spec section 4). Every cell is
 * focusable and carries a text label, suppressed cells are hatched and say "not enough data",
 * and a table view repeats everything, so color is never the only signal (section 6).
 * Server-rendered SVG: no JavaScript.
 */
import type { Schemas } from "@/lib/api/client";
import { count, percent, percentRange } from "@/lib/format";
import { t } from "@/lib/messages";
import { hourLabel } from "@/lib/time";

type Cell = Schemas["ReliabilityCell"];
type DayType = Cell["day_type"];

const DAYS: DayType[] = ["weekday", "saturday", "sunday"];
const HOURS = Array.from({ length: 24 }, (_, h) => h);
// Upper bounds of each color step for the missed rate, and their fills (light to dark).
export const STEPS = [0.02, 0.05, 0.1, 0.2, Infinity] as const;
const FILLS = ["#fde68a", "#fbbf24", "#f97316", "#dc2626", "#7f1d1d"];
const STEP_LABELS = ["under 2%", "2 to 5%", "5 to 10%", "10 to 20%", "20% or more"];

export function stepFor(rate: number): number {
  return STEPS.findIndex((upper) => rate < upper);
}

export function cellLabel(day: DayType, hour: number, cell: Cell | undefined): string {
  const vars = { day: t(`day.${day}`), hour: hourLabel(hour) };
  if (!cell || cell.n_trips === 0) return t("heatmap.cellEmpty", vars);
  if (cell.suppressed || cell.missed_rate === null) {
    return t("heatmap.cellSuppressed", { ...vars, trips: count(cell.n_trips) });
  }
  const range = percentRange(cell.ci_low, cell.ci_high);
  const base = t("heatmap.cell", {
    ...vars,
    percent: percent(cell.missed_rate),
    trips: count(cell.n_trips),
  });
  return range ? base + t("heatmap.cellRange", { range }) : base;
}

const SIZE = 12;
const GAP = 2;
const LEFT = 64;
const TOP = 14;

/** `id` keeps the hatch pattern's id unique when a page shows several heatmaps. */
export function ReliabilityHeatmap({ cells, id }: { cells: Cell[]; id: string }) {
  const hatch = `${id}-hatch`;
  const byKey = new Map(cells.map((c) => [`${c.day_type}-${c.hour_local}`, c]));
  const width = LEFT + HOURS.length * (SIZE + GAP);
  const height = TOP + DAYS.length * (SIZE + GAP);
  return (
    <figure>
      <figcaption className="mb-2 text-sm text-muted">{t("heatmap.caption")}</figcaption>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="group"
        aria-label={t("heatmap.caption")}
      >
        <defs>
          <pattern
            id="hatch"
            width="4"
            height="4"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <rect width="4" height="4" fill="var(--bg)" />
            <line x1="0" y1="0" x2="0" y2="4" stroke="var(--muted)" strokeWidth="1.5" />
          </pattern>
        </defs>
        {HOURS.filter((h) => h % 6 === 0).map((h) => (
          <text key={h} x={LEFT + h * (SIZE + GAP)} y={TOP - 4} fontSize="8" fill="var(--muted)">
            {hourLabel(h)}
          </text>
        ))}
        {DAYS.map((day, row) => (
          <g key={day}>
            <text x={0} y={TOP + row * (SIZE + GAP) + SIZE - 2} fontSize="9" fill="var(--fg)">
              {t(`day.${day}`)}
            </text>
            {HOURS.map((hour) => {
              const cell = byKey.get(`${day}-${hour}`);
              const label = cellLabel(day, hour, cell);
              const empty = !cell || cell.n_trips === 0;
              const hidden = !empty && (cell.suppressed || cell.missed_rate === null);
              const fill = empty
                ? "none"
                : hidden
                  ? `url(#${hatch})`
                  : FILLS[stepFor(cell.missed_rate ?? 0)];
              return (
                <rect
                  key={hour}
                  x={LEFT + hour * (SIZE + GAP)}
                  y={TOP + row * (SIZE + GAP)}
                  width={SIZE}
                  height={SIZE}
                  rx={2}
                  fill={fill}
                  stroke="var(--border)"
                  tabIndex={empty ? undefined : 0}
                  role="img"
                  aria-label={label}
                  className="focus:outline-2 focus:outline-accent"
                  data-state={empty ? "empty" : hidden ? "suppressed" : "rate"}
                >
                  <title>{label}</title>
                </rect>
              );
            })}
          </g>
        ))}
      </svg>
      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted" aria-hidden="true">
        {STEP_LABELS.map((label, i) => (
          <li key={label} className="flex items-center gap-1">
            <span className="inline-block size-3 rounded-sm" style={{ background: FILLS[i] }} />
            {label}
          </li>
        ))}
        <li className="flex items-center gap-1">
          <svg className="size-3" viewBox="0 0 12 12">
            <rect width="12" height="12" fill={`url(#${hatch})`} stroke="var(--border)" />
          </svg>
          {t("heatmap.legendSuppressed")}
        </li>
      </ul>
      <details className="mt-3">
        <summary className="flex min-h-11 cursor-pointer items-center text-sm text-accent">
          {t("heatmap.viewTable")}
        </summary>
        <table className="mt-2 w-full text-left text-sm">
          <thead>
            <tr>
              <th scope="col">{t("heatmap.hour")}</th>
              {DAYS.map((day) => (
                <th key={day} scope="col">
                  {t(`day.${day}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {HOURS.map((hour) => (
              <tr key={hour} className="border-t border-border">
                <th scope="row" className="py-1 font-normal">
                  {hourLabel(hour)}
                </th>
                {DAYS.map((day) => {
                  const cell = byKey.get(`${day}-${hour}`);
                  return <td key={day}>{tableText(cell)}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

function tableText(cell: Cell | undefined): string {
  if (!cell || cell.n_trips === 0) return "–";
  if (cell.suppressed || cell.missed_rate === null) return t("heatmap.legendSuppressed");
  return `${percent(cell.missed_rate)} of ${count(cell.n_trips)}`;
}
