/** Currently announced cancellations, soonest first (web spec section 4; ADR-029). */
import type { Schemas } from "@/lib/api/client";
import { t } from "@/lib/messages";
import { localTime } from "@/lib/time";

export function noticeText(seconds: number | null): string | null {
  if (seconds === null) return null;
  if (seconds < 0) return t("cancellations.afterDeparture");
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t("cancellations.posted", { minutes });
  return t("cancellations.postedHours", { hours: Math.floor(minutes / 60), minutes: minutes % 60 });
}

export function CancellationList({ data }: { data: Schemas["CurrentCancellations"] }) {
  return (
    <section aria-labelledby="cancellations">
      <h2 id="cancellations" className="text-lg font-semibold">
        {t("cancellations.heading")}
      </h2>
      {data.stale && data.as_of && (
        <p role="status" className="mt-1 text-sm">
          {t("cancellations.stale", { time: localTime(data.as_of) })}
        </p>
      )}
      {data.cancellations.length === 0 ? (
        <p className="mt-1 text-muted">{t("cancellations.none")}</p>
      ) : (
        <ul className="mt-2 divide-y divide-border">
          {data.cancellations.map((c) => (
            <li key={`${c.service_date}-${c.trip_id}`} className="py-2">
              <span className="font-medium">
                {c.headsign
                  ? t("cancellations.trip", {
                      time: localTime(c.sched_start),
                      headsign: c.headsign,
                    })
                  : t("cancellations.tripNoHeadsign", { time: localTime(c.sched_start) })}
              </span>
              {noticeText(c.advance_notice_s) && (
                <span className="block text-sm text-muted">{noticeText(c.advance_notice_s)}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {data.as_of && !data.stale && (
        <p className="mt-1 text-xs text-muted">
          {t("cancellations.asOf", { time: localTime(data.as_of) })}
        </p>
      )}
    </section>
  );
}
