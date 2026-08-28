/**
 * WO-02 — a stand-in for `next/font/local` under vitest.
 *
 * `next/font/local` is not a runtime function. Next replaces the call at
 * build time with a generated module: it reads the woff2 files, emits the
 * @font-face rules and hands back the class names that carry them. Imported
 * outside a Next build -- which is what any test that touches app/layout.tsx
 * does -- the real module resolves to a stub that throws.
 *
 * This replacement keeps the one property the tests actually rely on: the
 * returned `variable` is derived from the requested custom property, so an
 * assertion about which variables the layout puts in scope still means
 * something. It deliberately does NOT read or validate the font files;
 * `npm run build` is what proves those resolve, and
 * web/tests/fonts.test.ts checks their presence directly.
 *
 * Wired in by the `next/font/local` alias in vitest.config.mts.
 */

interface LocalFontOptions {
  variable?: string;
  src?: unknown;
  display?: string;
  preload?: boolean;
  adjustFontFallback?: false | string;
}

export default function localFont(options: LocalFontOptions) {
  const slug = String(options.variable ?? "--font-anonymous").replace(/[^a-zA-Z0-9]+/g, "_");
  return {
    className: `__className${slug}`,
    variable: `__variable${slug}`,
    style: { fontFamily: `"__stub${slug}"` },
  };
}
