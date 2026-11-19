"use client";

/** Any page whose data can't load (web spec section 4: error state with retry). reset() alone
 * only re-renders the boundary; refresh() re-runs the server render that failed. */
import { useRouter } from "next/navigation";
import { startTransition } from "react";

import { t } from "@/lib/messages";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  const router = useRouter();
  const retry = () =>
    startTransition(() => {
      router.refresh();
      reset();
    });
  return (
    <section role="alert">
      <p>{t("error.unavailable")}</p>
      <button
        type="button"
        onClick={retry}
        className="mt-3 min-h-11 rounded border border-border px-4"
      >
        {t("error.retry")}
      </button>
    </section>
  );
}
