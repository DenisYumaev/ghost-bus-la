import type { Metadata, Viewport } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { t } from "@/lib/messages";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: t("site.name"), template: `%s · ${t("site.name")}` },
  description: t("site.tagline"),
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="mx-auto flex min-h-screen max-w-3xl flex-col px-4 font-sans">
        <header className="border-b border-border py-4">
          <Link href="/" className="text-lg font-semibold">
            {t("site.name")}
          </Link>
        </header>
        <main className="flex-1 py-6">{children}</main>
        <footer className="border-t border-border py-4 text-sm text-muted">
          {t("site.disclaimer")}
        </footer>
      </body>
    </html>
  );
}
