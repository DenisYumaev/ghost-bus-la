/**
 * The line page (web spec section 3): the answer first, then announced cancellations, then each
 * direction's hour-by-day grid. Server-rendered and generated on first request (ISR), with no
 * client components. The 60 s cancellations fetch sets the page's revalidate to 60 s (the lowest
 * fetch revalidate wins); the detail and grid fetches are served from the fetch cache for 300 s.
 * There is no loading.tsx: a cached page arrives complete. If regeneration keeps failing, Next
 * serves the last good page, whose stale notice was computed when it was built (a known limit).
 */
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CancellationList } from "@/components/CancellationList";
import { LineSummary, periodText } from "@/components/LineSummary";
import { StaleNotice } from "@/components/StaleNotice";
import { ReliabilityHeatmap } from "@/components/charts/ReliabilityHeatmap";
import { ApiError, apiGet, orNull } from "@/lib/api/client";
import { percent } from "@/lib/format";
import { t } from "@/lib/messages";

export const revalidate = 300;

// No line is built ahead of time: the build needs no API, and each page is cached once visited.
export async function generateStaticParams(): Promise<{ line: string }[]> {
  return [];
}

type Props = { params: Promise<{ line: string }> };

/** Only a 404 means the line doesn't exist. A 503 (database down) must reach the error page,
 * never "we couldn't find that line". */
async function lineDetail(line: string) {
  try {
    return await apiGet("/v1/lines/{line}", { params: { line } });
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { line } = await params;
  const detail = await lineDetail(line);
  const name = detail.display_name;
  const summary =
    detail.summary.suppressed || detail.summary.missed_rate === null
      ? t("line.metaDescription", { name })
      : t("line.summary", {
          name,
          period: periodText(detail.summary.n_service_days),
          percent: percent(detail.summary.missed_rate),
        });
  return { title: t("line.metaTitle", { name }), description: summary };
}

export default async function LinePage({ params }: Props) {
  const { line } = await params;
  const detail = await lineDetail(line);
  const [grids, cancellations] = await Promise.all([
    Promise.all(
      detail.directions.map((d) =>
        orNull(
          apiGet("/v1/lines/{line}/reliability", {
            params: { line },
            query: { direction_id: d.direction_id },
          }),
        ),
      ),
    ),
    orNull(apiGet("/v1/cancellations/current", { query: { line }, revalidate: 60 })),
  ]);
  const name = detail.display_name;

  return (
    <article className="space-y-8">
      <header className="space-y-3">
        <h1 className="text-2xl font-bold">{t("line.title", { name })}</h1>
        {detail.line_kind && <p className="text-sm text-muted">{detail.line_kind}</p>}
        <StaleNotice dataAsOf={detail.data_as_of} now={new Date()} />
        <LineSummary name={name} rates={detail.summary} />
        <Link
          href="/method"
          className="inline-flex min-h-11 items-center text-sm text-accent underline"
        >
          {t("line.methodLink")}
        </Link>
      </header>

      {cancellations ? (
        <CancellationList data={cancellations} />
      ) : (
        <section aria-labelledby="cancellations">
          <h2 id="cancellations" className="text-lg font-semibold">
            {t("cancellations.heading")}
          </h2>
          <p role="status" className="mt-1 text-muted">
            {t("cancellations.unavailable")}
          </p>
        </section>
      )}

      {detail.directions.length > 1 && (
        <nav aria-label={t("line.directionsNav")} className="flex flex-wrap gap-2">
          {detail.directions.map((d) => (
            <a
              key={d.direction_id}
              href={`#direction-${d.direction_id}`}
              className="inline-flex min-h-11 items-center rounded border border-border px-3 text-sm"
            >
              {t("line.direction", { headsign: d.headsign })}
            </a>
          ))}
        </nav>
      )}

      {detail.directions.map((d, i) => {
        const grid = grids[i];
        return (
          <section key={d.direction_id} id={`direction-${d.direction_id}`} className="space-y-2">
            <h2 className="text-lg font-semibold">
              {t("line.direction", { headsign: d.headsign })}
            </h2>
            <h3 className="text-sm font-medium">{t("heatmap.heading")}</h3>
            {grid ? (
              <ReliabilityHeatmap cells={grid.cells} id={`direction-${d.direction_id}`} />
            ) : (
              <p className="text-muted">{t("line.noDirectionData")}</p>
            )}
          </section>
        );
      })}
    </article>
  );
}
