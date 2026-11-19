/** Shown when a response's data_as_of is older than an hour (web spec section 4). */
import { t } from "@/lib/messages";
import { isStale, localDay, localTime } from "@/lib/time";

export function StaleNotice({ dataAsOf, now }: { dataAsOf: string; now: Date }) {
  if (!isStale(dataAsOf, now)) return null;
  return (
    <p role="status" className="rounded border border-border p-2 text-sm">
      {t("stale.notice", { day: localDay(dataAsOf), time: localTime(dataAsOf) })}
    </p>
  );
}
