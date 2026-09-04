/**
 * The landing entry's link must not prefetch, and this is the only gate that
 * can say so per PR.
 *
 * WHY IT NEEDS ITS OWN FILE AND ITS OWN MOCK. The claim is about a prop that
 * `next/link` consumes and never renders: with `prefetch={false}` the DOM is
 * an `<a href="/learn">`, byte for byte what the default produces. So there
 * is nothing for `tests/features/LearnSurfaces.test.tsx` to assert — that
 * file renders the real `next/link` on purpose, because its other cases are
 * about `href`s — and a prop-capturing mock is file-scoped. Hence a second
 * file rather than a mock that would change what four other surfaces render.
 *
 * WHY THE PROP IS LOAD-BEARING. Every document route here is dynamically
 * rendered — `app/layout.tsx` reads the CSP nonce out of `headers()` — so
 * Next serves each one, RSC payload included, with `Cache-Control:
 * ...no-store...`. A *script-initiated* request that comes back `no-store`
 * blocks the back/forward cache on its own, and Chrome names it separately:
 * `JsNetworkRequestReceivedCacheControlNoStoreResource`. The App Router's
 * default prefetch fires this link as soon as `/` settles at 412 x 823, so
 * between WO-W12 and this repair the `bf-cache` audit failed on `/` and
 * passed on all three `/c/[id]` states, which have no in-viewport link.
 *
 * `web/lighthouserc.json` asserts that audit at `error` on every mobile cell
 * under RC-18 — but only in the nightly, against the full Compose stack. A
 * one-word regression here would therefore be a day old at best and a
 * disabled workflow at worst, which is exactly what happened. This test is
 * the per-PR half.
 */

import { describe, expect, it, vi } from "vitest";

import { LearnLandingEntry } from "@/components/features/LearnLandingEntry";
import { LEARN } from "@/lib/copy/learn";

import { render, screen } from "../support/render";

// The prop the DOM never shows, made visible. Nothing else about the element
// changes, so the `href` assertion below is still the real one.
vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    prefetch,
    ...rest
  }: {
    children: React.ReactNode;
    href: string;
    prefetch?: boolean;
  } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} data-test-prefetch={String(prefetch)} {...rest}>
      {children}
    </a>
  ),
}));

describe("the landing entry's link into the guided-reading surface", () => {
  it("points at /learn and does not prefetch it", () => {
    render(<LearnLandingEntry />);

    const link = screen.getByRole("link", { name: LEARN.landingAction });
    expect(link).toHaveAttribute("href", "/learn");
    // `false`, not `undefined`: an omitted prop is the App Router default,
    // which is the prefetch this route cannot afford.
    expect(link).toHaveAttribute("data-test-prefetch", "false");
  });
});
