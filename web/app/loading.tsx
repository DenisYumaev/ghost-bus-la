/** Shown while a page renders on the server (web spec section 4: loading state). */
import { t } from "@/lib/messages";

export default function Loading() {
  return (
    <div aria-busy="true" className="space-y-3">
      <p className="sr-only">{t("loading")}</p>
      <div className="h-8 w-2/3 animate-pulse rounded bg-border" />
      <div className="h-4 w-full animate-pulse rounded bg-border" />
      <div className="h-4 w-5/6 animate-pulse rounded bg-border" />
    </div>
  );
}
