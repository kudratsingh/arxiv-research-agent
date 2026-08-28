import type { Metadata } from "next";

import { themeInitScript } from "@/lib/tokens";

import { fontVariables } from "./fonts/fonts";

// The metric-adjusted fallback faces. Imported here rather than from
// globals.css because they belong to the font declarations below, not to
// the token sheet: WO-01 owns tokens.css, WO-02 owns app/fonts/.
import "./fonts/fallback.css";
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
    // className carries the three next/font/local variables --font-ui-face,
    // --font-report-face and --font-mono-face. They sit at the head of the
    // --font-* stacks in tokens.css, so every family in the product resolves
    // through this element.
    <html lang="en" className={fontVariables} suppressHydrationWarning>
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
