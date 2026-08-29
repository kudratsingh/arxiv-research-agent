/**
 * GlobalErrorSurface — the body of `app/global-error.tsx` (WO-09
 * criterion 5).
 *
 * THIS IS THE ONE COMPONENT IN THE PRODUCT THAT MUST SURVIVE A BROKEN
 * STYLESHEET, and the work order says so in its risk note: "`global-error.tsx`
 * is the one surface that must survive a broken stylesheet. Its story is
 * rendered with tokens deliberately absent."
 *
 * The reason is structural, not defensive. A global error boundary replaces
 * `<html>` itself, so the root layout is gone — and with it the `<head>`
 * that loaded `app/globals.css`, the class that carries the three
 * `next/font/local` variables, and the pre-paint script that writes
 * `data-theme`. Every `--color-*`, `--space-*` and `--text-*` custom
 * property is therefore undefined on this surface. A `class="bg-canvas
 * text-ink"` here does not degrade gracefully: `var(--color-canvas)` with
 * no fallback resolves to nothing, and the surface that exists to report a
 * catastrophic failure renders as unstyled black-on-transparent — or, if
 * the failure *was* the stylesheet, as nothing at all.
 *
 * SO IT IMPORTS NO CSS AND USES NO TOKEN. Three rules, all of which
 * web/tests/shell/recovery.test.tsx asserts against this file's own source
 * text:
 *
 *   1. no `import "….css"` anywhere in this module or in
 *      `app/global-error.tsx`;
 *   2. no `var(--…)` in any value;
 *   3. no Tailwind utility that resolves to a custom property — which is
 *      every colour, space and type utility in this design system, so the
 *      rule is simply: no `className` at all.
 *
 * AND IT NAMES NO TYPEFACE EITHER — not even `system-ui`. WO-02's font gate
 * (`web/tests/fonts.test.ts`) allows a family name in `app/tokens.css` and
 * nowhere else under `web/`, and that rule generalises to this surface
 * rather than merely constraining it: the three `--font-*` stacks are
 * `next/font/local` variables carried by a class on the `<html>` element
 * this boundary replaces, so naming a family here would be naming one that
 * cannot resolve. What is left is the user agent's own default, which is
 * the only text rendering guaranteed to exist when nothing has loaded. Size
 * and leading are set; the face is not.
 *
 * WHAT IT USES INSTEAD: CSS system colours (`Canvas`, `CanvasText`,
 * `ButtonFace`, `ButtonText`, `GrayText`) plus `color-scheme: light dark`.
 * These are defined by the user agent, not by any stylesheet, so they are
 * available when nothing has loaded; they follow the OS light/dark
 * preference through `color-scheme` without the theme script; and under
 * forced colours they are already the user's own palette rather than
 * something to be overridden. That is a strictly better answer here than a
 * hard-coded hex would be — and a hex is not available anyway, because
 * `app/tokens.css` is the only file in `web/` allowed to contain one
 * (WO-01, `tokens/no-literal-colour`, `web/tests/tokens.test.ts`).
 *
 * NOT A LIVE REGION, AND NO `role="alert"`. 03 §7.3 allows two product-wide
 * and both are spoken for. This surface *is* the document; a screen reader
 * arrives at it by load, and the `h1` is what tells it where it is.
 *
 * IT CARRIES NO STRINGS OF ITS OWN — `GLOBAL_ERROR` in
 * web/lib/copy/globalError.ts, held to WO-12's gate by
 * web/tests/copy/recovery-copy.test.ts. That import is a plain TypeScript
 * module with no stylesheet and no token behind it, so it is safe on this
 * surface in a way that a component import would not be.
 */

import type { CSSProperties } from "react";

import { GLOBAL_ERROR } from "@/lib/copy/globalError";

/**
 * `light dark` is what makes the system colours below follow the operating
 * system's preference with no `data-theme`, no script and no stylesheet.
 */
const PAGE: CSSProperties = {
  colorScheme: "light dark",
  background: "Canvas",
  color: "CanvasText",
  minHeight: "100vh",
  boxSizing: "border-box",
  padding: "48px 24px",
  fontSize: "16px",
  lineHeight: 1.5,
};

const FRAME: CSSProperties = {
  margin: "0 auto",
  maxWidth: "60ch",
  display: "flex",
  flexDirection: "column",
  gap: "16px",
  alignItems: "flex-start",
};

const HEADING: CSSProperties = {
  margin: 0,
  fontSize: "24px",
  lineHeight: 1.25,
  fontWeight: 600,
};

const BODY: CSSProperties = { margin: 0 };

/**
 * `CanvasText`, not `GrayText`. `GrayText` is the user agent's DISABLED
 * colour, and it is allowed to be low-contrast by definition — axe-core
 * 4.13.0 in headless Chrome scores `GrayText` on `Canvas` as a serious
 * `color-contrast` violation on this very surface. There is no muted role
 * in the system-colour vocabulary, and inventing one out of `color-mix`
 * would be inventing a value this surface cannot verify. So the secondary
 * lines are the same ink as the primary ones, and size is what separates
 * them.
 */
const DETAIL: CSSProperties = { margin: 0 };

const REFERENCE: CSSProperties = {
  margin: 0,
  fontSize: "14px",
  wordBreak: "break-all",
};

/**
 * A user-agent-styled button with the minimum on top of it. The 44px
 * minimum height is 03 §7.4's coarse-pointer target floor written as a
 * literal, because the `--size-*` tokens it normally comes from are not
 * defined on this surface either.
 */
const ACTION: CSSProperties = {
  background: "ButtonFace",
  color: "ButtonText",
  border: "1px solid ButtonBorder",
  borderRadius: "6px",
  minHeight: "44px",
  padding: "0 16px",
  font: "inherit",
  fontWeight: 500,
  cursor: "pointer",
};

export interface GlobalErrorSurfaceProps {
  /** `error.digest`, when the runtime produced one. */
  digest?: string;
  /** Reloads the document. The boundary's own `reset()` cannot help here. */
  onReload: () => void;
}

export function GlobalErrorSurface({ digest, onReload }: GlobalErrorSurfaceProps) {
  return (
    <div style={PAGE} data-recovery-surface="global-error">
      {/*
        A `<main>`, even here. This surface has no shell, so it has no
        landmarks unless it renders its own — and `landmark-one-main` and
        `region` are exactly the two rules that fail in 12 of 12 Gate 1 axe
        reports (03 §7.1). Measured with axe-core 4.13.0 in headless Chrome:
        without this element the global boundary is a `landmark-one-main`
        violation and four `region` violations; with it, the surface is
        clean. One `<main>` is not a shell — it is the minimum a document
        owes a screen reader.
      */}
      <main style={FRAME}>
        <h1 style={HEADING}>{GLOBAL_ERROR.heading}</h1>
        <p style={BODY}>{GLOBAL_ERROR.body}</p>
        <p style={DETAIL}>{GLOBAL_ERROR.detail}</p>

        {digest === undefined || digest === "" ? null : (
          <p style={REFERENCE} data-error-digest="">
            {GLOBAL_ERROR.referenceLabel}: {digest}
          </p>
        )}

        <button type="button" style={ACTION} onClick={onReload}>
          {GLOBAL_ERROR.action}
        </button>
      </main>
    </div>
  );
}
