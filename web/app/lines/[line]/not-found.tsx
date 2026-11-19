import Link from "next/link";

import { t } from "@/lib/messages";

export default function LineNotFound() {
  return (
    <section>
      <h1 className="text-xl font-semibold">{t("notFound.line")}</h1>
      <Link href="/" className="mt-2 inline-flex min-h-11 items-center text-accent underline">
        {t("site.name")}
      </Link>
    </section>
  );
}
