/**
 * All lines (web spec section 3): searchable by number, sortable by reliability. Plain links and a
 * GET form, so it works with no JavaScript.
 */
import type { Metadata } from "next";
import Link from "next/link";

import { apiGet } from "@/lib/api/client";
import { NOT_ENOUGH_DATA, percent, percentRange } from "@/lib/format";
import { byReliability, matching, rateOf } from "@/lib/lines";
import { StaleNotice } from "@/components/StaleNotice";
import { t } from "@/lib/messages";
import { serviceDay } from "@/lib/time";

export const metadata: Metadata = { title: t("lines.title") };

type Props = { searchParams: Promise<{ q?: string; sort?: string }> };

function RateText({ line, rate }: { line: Parameters<typeof rateOf>[0]; rate: number | null }) {
  if (rate === null) return <>{NOT_ENOUGH_DATA}</>;
  const range = percentRange(line.summary.missed_rate_ci_low, line.summary.missed_rate_ci_high);
  const days = line.summary.n_service_days;
  return (
    <>
      {t("lines.neverRan", { percent: percent(rate) })}
      {range && <span className="block text-muted">{t("lines.range", { range })}</span>}
      {days !== null && days < 28 && (
        <span className="block text-muted">{t("lines.days", { days })}</span>
      )}
    </>
  );
}

export default async function LinesPage({ searchParams }: Props) {
  const { q = "", sort } = await searchParams;
  const data = await apiGet("/v1/lines");
  const found = matching(data.lines, q);
  const lines = sort === "reliability" ? byReliability(found) : found;
  const sortLink = (value: string | null) => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (value) params.set("sort", value);
    const query = params.toString();
    return query ? `/lines?${query}` : "/lines";
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">{t("lines.title")}</h1>
      <StaleNotice dataAsOf={data.data_as_of} now={new Date()} />
      {data.data_through && (
        <p className="text-muted">{t("lines.intro", { date: serviceDay(data.data_through) })}</p>
      )}
      <form action="/lines" method="get" role="search" className="flex gap-2">
        <label htmlFor="q" className="sr-only">
          {t("home.searchLabel")}
        </label>
        <input
          id="q"
          name="q"
          defaultValue={q}
          placeholder={t("home.searchLabel")}
          className="min-h-11 flex-1 rounded border border-border bg-bg px-3"
        />
        {sort && <input type="hidden" name="sort" value={sort} />}
        <button type="submit" className="min-h-11 rounded bg-accent px-4 font-medium text-bg">
          {t("home.searchButton")}
        </button>
      </form>
      <nav aria-label={t("lines.sortLabel")} className="flex gap-2 text-sm">
        <Link
          href={sortLink(null)}
          aria-current={sort !== "reliability" ? "true" : undefined}
          className="inline-flex min-h-11 items-center rounded border border-border px-3 aria-[current=true]:font-semibold"
        >
          {t("lines.sortNumber")}
        </Link>
        <Link
          href={sortLink("reliability")}
          aria-current={sort === "reliability" ? "true" : undefined}
          className="inline-flex min-h-11 items-center rounded border border-border px-3 aria-[current=true]:font-semibold"
        >
          {t("lines.sortReliability")}
        </Link>
      </nav>
      {lines.length === 0 ? (
        <p>{q.trim() ? t("lines.noMatch", { q }) : t("lines.none")}</p>
      ) : (
        <>
          <p className="text-sm text-muted">
            {lines.length === 1 ? t("lines.countOne") : t("lines.count", { count: lines.length })}
          </p>
          <ul className="divide-y divide-border">
            {lines.map((line) => {
              const rate = rateOf(line);
              return (
                <li key={line.line}>
                  <Link
                    href={`/lines/${line.line_slug}`}
                    className="flex min-h-11 items-center justify-between gap-3 py-2"
                  >
                    <span>
                      <span className="font-semibold">
                        {t("line.title", { name: line.display_name })}
                      </span>
                      {line.line_kind && (
                        <span className="block text-sm text-muted">{line.line_kind}</span>
                      )}
                    </span>
                    <span className="text-right text-sm">
                      <RateText line={line} rate={rate} />
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
