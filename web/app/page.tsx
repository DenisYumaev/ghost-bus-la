import { t } from "@/lib/messages";

export default function Home() {
  return (
    <section>
      <h1 className="text-2xl font-bold">{t("site.tagline")}</h1>
      <p className="mt-2 text-muted">{t("home.comingSoon")}</p>
    </section>
  );
}
