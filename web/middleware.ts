import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import {
  NONCE_HEADER,
  buildCspPolicy,
  createNonce,
  cspHeaderName,
  cspModeFor,
} from "@/lib/server/csp";

/**
 * WO-30 — the per-request CSP nonce (05-MIGRATION.md C3, RC-07).
 *
 * THE FILE 04-ARCHITECTURE.md §10 SAID NOT TO CREATE, AND WHY IT EXISTS NOW.
 * Seam S3 reads "`web/middleware.ts` ... does not exist ... Not created now —
 * an empty middleware costs a hop on every request for no benefit." C3 needs
 * one anyway, because a nonce is per-request and `next.config.mjs`'s
 * `headers()` is static. RC-07 resolved the tension in C3's favour with a
 * condition attached, and the condition is the `matcher` at the bottom of
 * this file: the hop is paid only by document requests. `/api/*` — the
 * credential boundary, every SSE stream and every export download — takes no
 * extra hop at all, and neither does `/_next/static/*` or the icon. Those
 * three get their (static, nonce-free) headers from `next.config.mjs`
 * instead.
 *
 * It is also, exactly as C3 predicted, where MT-01's session check will go
 * (04 §10 seam S3). Nothing of MT-01 is implemented here — see
 * `lib/server/principal.ts` for the seam that IS built, and `docs/security.md`
 * for what remains out of scope.
 *
 * HOW THE NONCE REACHES THE SCRIPTS.
 *
 *   1. Next's own bundle tags: Next reads the CSP off the REQUEST headers and
 *      stamps the nonce onto every `<script>` it renders
 *      (`next/dist/server/app-render/app-render.js` — it accepts either the
 *      enforcing or the Report-Only header). That is why the policy is set on
 *      the outgoing request as well as on the response.
 *   2. The pre-paint theme script: `app/layout.tsx` reads `x-nonce` and puts
 *      it on the `<script>` element itself. Next does not nonce author
 *      markup, and under `'strict-dynamic'` an un-nonced inline script is
 *      refused — which would restore the exact theme flash WO-01 exists to
 *      prevent. `web/e2e/csp.spec.ts` asserts the themed first paint under
 *      the enforcing policy for that reason.
 *
 * A NOTE ON RENDERING MODE. Reading the nonce in the root layout opts every
 * document route into dynamic rendering, and that is not an accident of the
 * implementation — it is inherent. A per-request nonce cannot appear in a
 * statically cached HTML file, and a cached document whose script tags carry
 * a stale nonce is a document whose scripts are all refused. Nonce-based CSP
 * and full-page static generation are mutually exclusive; the PR body records
 * the `/` route flipping from `○` to `ƒ`.
 */
export function middleware(request: NextRequest): NextResponse {
  const mode = cspModeFor(process.env);
  const headerName = cspHeaderName(mode);
  if (headerName === null) return NextResponse.next();

  const nonce = createNonce();
  const policy = buildCspPolicy(nonce);

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(NONCE_HEADER, nonce);
  // Both, deliberately: `app/layout.tsx` reads the first, Next's renderer
  // reads the second. A request that arrived carrying either header from
  // outside is overwritten, not merged.
  requestHeaders.set(headerName, policy);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set(headerName, policy);
  return response;
}

/**
 * RC-07's condition, as configuration.
 *
 * The negative lookahead names exactly the three exclusions RC-07 requires —
 * `/api/*`, `/_next/static/*` and the icon — and nothing else. `/_next/image`
 * is deliberately absent: the app ships no `next/image` usage, so excluding a
 * route that is never requested would be a guess dressed as a rule.
 *
 * Everything else is a document, and every document gets the policy: that
 * includes `/`, `/c/[id]`, the 404 and the error boundaries. A page reachable
 * without a CSP is a page where the CSP is not a control.
 */
export const config = {
  matcher: ["/((?!api/|_next/static/|icon\\.svg).*)"],
};
