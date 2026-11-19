/** How trips are classified, in plain words, with the thresholds of the build in force. */
import type { Metadata } from "next";

import { apiGet } from "@/lib/api/client";
import { StaleNotice } from "@/components/StaleNotice";
import { t } from "@/lib/messages";

// Rendered per request, never at build: the build must not need the API (a VM outage would fail
// web deploys). The API responses themselves are cached on the server (fetch revalidate).
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: t("method.title") };

export default async function MethodPage() {
  const method = await apiGet("/v1/meta/method");
  return (
    <article className="space-y-6">
      <h1 className="text-2xl font-bold">{t("method.title")}</h1>
      <StaleNotice dataAsOf={method.data_as_of} now={new Date()} />
      <p>{t("method.intro")}</p>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">{t("method.outcomes")}</h2>
        <dl className="space-y-2">
          {method.outcomes.map((d) => (
            <div key={d.term}>
              <dt className="font-medium">{d.term}</dt>
              <dd className="text-muted">{d.meaning}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">{t("method.rates")}</h2>
        <dl className="space-y-2">
          {method.rates.map((d) => (
            <div key={d.term}>
              <dt className="font-medium">{d.term}</dt>
              <dd className="text-muted">{d.meaning}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">{t("method.thresholds")}</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                <th scope="col">{t("method.thresholdName")}</th>
                <th scope="col">{t("method.thresholdValue")}</th>
                <th scope="col">{t("method.thresholdWhy")}</th>
                <th scope="col">{t("method.thresholdDecision")}</th>
              </tr>
            </thead>
            <tbody>
              {method.thresholds.map((th) => (
                <tr key={th.name} className="border-t border-border align-top">
                  <th scope="row" className="py-1 pr-2 font-normal">
                    <code>{th.name}</code>
                  </th>
                  <td className="pr-2 whitespace-nowrap">
                    {th.value} {th.unit}
                  </td>
                  <td className="pr-2">{th.description}</td>
                  <td>{th.decision}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">{t("method.notes")}</h2>
        <ul className="list-disc space-y-1 pl-5">
          {method.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </section>
    </article>
  );
}
