/** The answer first (web spec section 1): one sentence, then its range and counts. */
import type { Schemas } from "@/lib/api/client";
import { count, percent, percentRange } from "@/lib/format";
import { t } from "@/lib/messages";

/** "the past 28 days", or the days actually covered while the archive is younger than that. */
export function periodText(serviceDays: number | null): string {
  if (serviceDays !== null && serviceDays < 28) return t("line.periodShort", { days: serviceDays });
  return t("line.period28");
}

export function LineSummary({ name, rates }: { name: string; rates: Schemas["Rates"] }) {
  if (rates.suppressed || rates.missed_rate === null) {
    return <p className="text-lg">{t("line.summarySuppressed", { name })}</p>;
  }
  const period = periodText(rates.n_service_days);
  const range = percentRange(rates.missed_rate_ci_low, rates.missed_rate_ci_high);
  return (
    <div>
      <p className="text-lg font-semibold">
        {t("line.summary", { name, period, percent: percent(rates.missed_rate) })}
      </p>
      {range && <p className="mt-1 text-muted">{t("line.summaryRange", { range })}</p>}
      <p className="mt-1 text-sm text-muted">
        {t("line.summaryCounts", {
          missed: count(rates.n_missed),
          trips: count(rates.n_trips),
          announced: count(rates.n_missed_announced),
          unplanned: count(rates.n_missed_unplanned),
        })}
      </p>
    </div>
  );
}
