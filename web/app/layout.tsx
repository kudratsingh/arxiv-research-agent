import type { Metadata } from "next";

import { themeInitScript } from "@/lib/tokens";

import "./globals.css";

export const metadata: Metadata = {
  title: "arxiv-research-agent",
  description:
    "Multi-agent research assistant for ML/AI papers. LangGraph + Claude with supervisor loop, faithfulness verifier, eval harness, FastAPI + SSE, Docker + Redis + Postgres.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // suppressHydrationWarning: the script below writes data-theme and
    // data-theme-preference onto this element before React hydrates, so
    // the server markup deliberately does not match.
    <html lang="en" suppressHydrationWarning>
      <head>
        {/*
          The pre-paint theme script. Inline and synchronous by
          necessity -- anything deferred paints the light theme first
          and flashes. Its source lives in web/lib/tokens.ts so the
          localStorage key has exactly one definition; WO-21 asserts the
          absence of the flash in Playwright, and C3's CSP will need to
          hand this element a nonce once web/middleware.ts exists.
        */}
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
