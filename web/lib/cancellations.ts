import { t } from "@/lib/messages";

/** The count with its time in the sentence: the list can lag the feed by up to about an hour
 * (ADR-029), so it never claims "right now". */
export function cancelledText(count: number, time: string): string {
  if (count === 0) return t("home.cancelledCountNone", { time });
  if (count === 1) return t("home.cancelledCountOne", { time });
  return t("home.cancelledCount", { time, count: count.toLocaleString("en-US") });
}
