import type { Metadata } from "next";

import { readCspNonce } from "@/lib/server/csp";
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

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // WO-30. `undefined` outside a request scope and in development, where
  // `cspModeFor` returns `off` and no script needs one; a fresh per-request
  // value under the enforcing policy. See lib/server/csp.ts.
  const nonce = await readCspNonce();

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
          absence of the flash in Playwright.

          WO-30 SUPPLIED THE NONCE THIS COMMENT USED TO PROMISE. Under
          `script-src 'self' 'nonce-...' 'strict-dynamic'` the `'self'`
          source is ignored by any browser that implements
          `'strict-dynamic'`, so an inline script with no nonce is
          refused outright -- which would mean no pre-paint theme, which
          is the flash. Next stamps its own bundle tags automatically
          (it reads the CSP off the request headers); author markup like
          this element is the one place the value has to be threaded by
          hand. web/e2e/csp.spec.ts asserts the themed first paint with
          the enforcing header live, so a dropped nonce goes red rather
          than quietly reintroducing the flash.
        */}
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      {/*
        WO-11's `<Providers>` IS NOT MOUNTED HERE, AND WO-08 MEASURED WHY.

        `web/app/providers.tsx` documents the intended edit — wrap `children`
        in `<Providers>` — and names WO-08 as the work order that would make
        it. WO-08 built the mount, measured it with `npm run budgets`, and
        took it back out:

            /        143,848 B -> 151,864 B   ceiling 148,480 B   BREACH
            /c/[id]  194,518 B -> 202,536 B   ceiling 199,680 B   BREACH

        TanStack Query in the root layout is +8,016 B gzip on `/` and
        +8,018 B on `/c/[id]`, and in M1 it has no consumer: every component
        the shell renders is a legacy one that calls `lib/api` directly. So
        the mount would breach two gated rows to load a library nothing
        reads, which is the ratchet rule's exact anti-pattern
        (04-ARCHITECTURE.md §8.4: a ceiling moves only in a PR that says
        why).

        providers.tsx's own note already says where it should land: "The
        ~13 KB gzip lands on `/` when WO-20 route-loads it, and WO-23's
        check is what will price it." WO-20 rewrites both pages against the
        query layer, so it is the PR where the bytes buy something and where
        the ceiling can be moved on the record. The edit is one line, here.
      */}
      <body>{children}</body>
    </html>
  );
}
