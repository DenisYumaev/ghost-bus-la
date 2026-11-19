/**
 * Home (web spec section 3): find a line, and how many trips are announced as canceled right now.
 * No system-wide percentage yet: the API marks those numbers internal until M5 checks them
 * against Metro's own report (API spec section 4.1), so line pages carry the public numbers.
 */
import Link from "next/link";

import { apiGet } from "@/lib/api/client";
import { cancelledText } from "@/lib/cancellations";
import { t } from "@/lib/messages";
import { localTime } from "@/lib/time";

// Rendered per request, never at build: the build must not need the API (a VM outage would fail
// web deploys). The API responses themselves are cached on the server (fetch revalidate).
export const dynamic = "force-dynamic";

export default async function Home() {
  // Any failure here only blanks this section: the search form needs no API at all.
  const current = await apiGet("/v1/cancellations/current", { revalidate: 60 }).catch(() => null);
  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h1 className="text-2xl font-bold">{t("site.tagline")}</h1>
        <p className="text-muted">{t("home.intro")}</p>
      </section>

      <form action="/lines" method="get" role="search" className="flex gap-2">
        <label htmlFor="q" className="sr-only">
          {t("home.searchLabel")}
        </label>
        <input
          id="q"
          name="q"
          placeholder={t("home.searchLabel")}
          className="min-h-11 flex-1 rounded border border-border bg-bg px-3"
        />
        <button type="submit" className="min-h-11 rounded bg-accent px-4 font-medium text-bg">
          {t("home.searchButton")}
        </button>
      </form>

      <section aria-labelledby="now" className="space-y-1">
        <h2 id="now" className="text-lg font-semibold">
          {t("cancellations.heading")}
        </h2>
        {current?.as_of && !current.stale ? (
          <>
            <p>{cancelledText(current.cancellations.length, localTime(current.as_of))}</p>
            <p className="text-sm text-muted">{t("home.cancelledLag")}</p>
          </>
        ) : current?.as_of ? (
          <p role="status">{t("cancellations.stale", { time: localTime(current.as_of) })}</p>
        ) : (
          <p role="status" className="text-muted">
            {t("home.cancelledUnavailable")}
          </p>
        )}
      </section>

      <Link href="/lines" className="inline-flex min-h-11 items-center text-accent underline">
        {t("home.allLines")}
      </Link>
    </div>
  );
}
