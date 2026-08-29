"use client";

/**
 * `app/global-error.tsx` — the last-resort boundary (04 §2.1, WO-09
 * criterion 5).
 *
 * It replaces the framework default, which is a blank page in production.
 * Next mounts this INSTEAD OF the root layout, so it has to render its own
 * `<html>` and `<body>` — which is also the whole reason criterion 5 exists:
 * with `app/layout.tsx` gone, so is the `<head>` that loaded
 * `app/globals.css`, the class carrying the three `next/font/local`
 * variables, and the pre-paint script that writes `data-theme`. Every
 * design token is undefined here.
 *
 * THIS FILE THEREFORE IMPORTS NO STYLESHEET AND NO TOKEN MODULE. Not
 * `./globals.css`, not `./fonts/fallback.css`, not `@/lib/tokens`, and not
 * any component that pulls one in transitively — which is every primitive
 * and every other pattern, because they all import
 * `components/primitives/primitives.css`. The one component it does render
 * is `GlobalErrorSurface`, which is built out of CSS system colours and
 * inline styles for exactly this reason; read its header for the argument.
 * `web/tests/shell/recovery.test.tsx` asserts the absence against both
 * files' source text, and `Shell/ErrorBoundary`'s `Global` story renders
 * the surface with the token sheet deliberately unset.
 *
 * NO SHELL, EITHER. `WorkbenchShell` is a client component that imports
 * `./workbench.css`, whose every colour is a `var(--color-*)`; rendering the
 * shell here would produce an invisible header and an invisible rail around
 * a message the user needs to read. The surface below is the whole document
 * on purpose.
 *
 * `<title>` IS RENDERED IN THE TREE, NOT EXPORTED AS METADATA. A client
 * component cannot export `metadata`, and this document has no layout to
 * inherit one from. React 19 hoists a `<title>` element into `<head>`
 * wherever it appears, which is the mechanism that gives a tab-crashed page
 * a name instead of the URL.
 *
 * THE ACTION IS A RELOAD, NOT `reset()`. Next hands this boundary a `reset`
 * that re-renders the tree that just threw — the root layout, in this case,
 * which is the thing that failed. If the failure was the stylesheet or the
 * font manifest, re-rendering the same document cannot fix it and a fresh
 * request can. So the copy says "Reload this page" and the control does
 * exactly that; `reset` is deliberately left unused rather than wired to a
 * control that would usually fail again in place.
 */

import { GlobalErrorSurface } from "@/components/patterns/GlobalErrorSurface";
import { GLOBAL_ERROR } from "@/lib/copy/globalError";

export default function GlobalError({
  error,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    // `lang` is on this element rather than inherited, because there is no
    // root layout left to inherit it from. `html-has-lang` is an axe rule
    // that this surface would otherwise be the only page in the product to
    // fail.
    <html lang="en">
      <body>
        <title>{GLOBAL_ERROR.documentTitle}</title>
        <GlobalErrorSurface
          digest={error.digest}
          onReload={() => {
            window.location.reload();
          }}
        />
      </body>
    </html>
  );
}
