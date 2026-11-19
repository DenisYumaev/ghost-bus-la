/** Feed health for the past 7 days and the last publish (web spec section 3; revalidate 60 s). */
import type { Metadata } from "next";

import { apiGet } from "@/lib/api/client";
import { percent } from "@/lib/format";
import { healthByDay } from "@/lib/health";
import { StaleNotice } from "@/components/StaleNotice";
import { t } from "@/lib/messages";
import { localDay, localTime } from "@/lib/time";

// Rendered per request, never at build: the build must not need the API (a VM outage would fail
// web deploys). The API responses themselves are cached on the server (fetch revalidate).
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: t("status.title") };

const FEEDS = ["vehicle_positions", "trip_updates"] as const;
const FEED_LABEL = {
  vehicle_positions: t("status.feed.vehicle_positions"),
  trip_updates: t("status.feed.trip_updates"),
};

export default async function StatusPage() {
  const health = await apiGet("/v1/system/feed-health", { query: { hours: 168 }, revalidate: 60 });
  const rows = healthByDay(health.buckets);
  return (
    <article className="space-y-4">
      <h1 className="text-2xl font-bold">{t("status.title")}</h1>
      <p>{t("status.intro")}</p>
      <StaleNotice dataAsOf={health.data_as_of} now={new Date()} />
      <p className="text-sm text-muted">
        {t("status.lastRefresh", {
          day: localDay(health.data_as_of),
          time: localTime(health.data_as_of),
        })}
      </p>
      {rows.length === 0 ? (
        <p>{t("status.none")}</p>
      ) : (
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{t("status.caption")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("status.day")}</th>
              {FEEDS.map((feed) => (
                <th key={feed} scope="col">
                  {FEED_LABEL[feed]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.day} className="border-t border-border">
                <th scope="row" className="py-1 font-normal">
                  {row.partial ? t("status.partial", { day: row.label }) : row.label}
                </th>
                {FEEDS.map((feed) => {
                  const share = row.healthy[feed];
                  return (
                    <td key={feed}>
                      {share === undefined
                        ? t("status.noData")
                        : t("status.healthyShare", { percent: percent(share) })}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </article>
  );
}
