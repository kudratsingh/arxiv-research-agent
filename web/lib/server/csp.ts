/**
 * The Content Security Policy, its per-request nonce, and the one place both
 * are written down (WO-30, 05-MIGRATION.md C3, RC-07).
 *
 * WHY A MODULE AND NOT A STRING IN `middleware.ts`. Three consumers need the
 * same policy and would otherwise each keep a copy: the middleware that sets
 * the header, `app/layout.tsx` which needs the nonce the middleware minted,
 * and `web/tests/csp.test.ts` + `web/e2e/csp.spec.ts` which assert the policy
 * is *exactly* C3's. A policy asserted against a second transcription of
 * itself is not asserted at all, so the directive table below is the only
 * copy in the repository and every assertion reads it from here.
 *
 * WHY THE POLICY NEEDS A MIDDLEWARE AT ALL. `script-src` carries a nonce, and
 * a nonce is per-request, so it cannot come from `next.config.mjs`'s static
 * `headers()`. RC-07 records the tension this creates with
 * 04-ARCHITECTURE.md §10 seam S3 ("middleware ... Not created now — an empty
 * middleware costs a hop on every request for no benefit") and resolves it:
 * the middleware is created for the nonce, and its `matcher` excludes
 * `/api/*`, `/_next/static/*` and the icon so the hop is never paid by proxy
 * or asset traffic.
 */

/** Where `middleware.ts` puts the nonce for `app/layout.tsx` to read. */
export const NONCE_HEADER = "x-nonce";

/** The enforcing header. */
export const CSP_HEADER = "content-security-policy";

/**
 * The observe-only header. Next reads the nonce out of EITHER header
 * (`next/dist/server/app-render/app-render.js`: `headers['content-security-
 * policy'] || headers['content-security-policy-report-only']`), which is what
 * makes criterion 1's "Report-Only first, then enforce" a header-name switch
 * rather than two different renders.
 */
export const CSP_REPORT_ONLY_HEADER = "content-security-policy-report-only";

/**
 * How the policy is applied to a response.
 *
 * `off` exists for `next dev` and nothing else — see `cspModeFor` below.
 */
export type CspMode = "enforce" | "report-only" | "off";

/** Environment variable that overrides the per-environment default. */
export const CSP_MODE_ENV = "CSP_MODE";

/**
 * 05-MIGRATION.md C3's policy, directive by directive, with the reason each
 * one is what it is. `{nonce}` is substituted per request.
 *
 * Every one of C3's ten directives is here verbatim — none was removed and
 * none was widened. There is exactly ONE addition, `style-src-attr`, and the
 * comment on it records the Report-Only measurement that produced it.
 * `web/tests/csp.test.ts` compares the rendered string against C3's sentence
 * transcribed independently, so a directive cannot drift without a red test,
 * and it asserts that the addition is that single directive and no other.
 */
const DIRECTIVES: readonly (readonly [string, string])[] = [
  // Everything falls back to same-origin. The app loads no third-party
  // anything: no analytics SDK, no error-tracking SaaS, no CDN font
  // (04-ARCHITECTURE.md §9.2, "Nothing is transmitted anywhere").
  ["default-src", "'self'"],
  // `'strict-dynamic'` makes the nonce the whole allowlist: under CSP3 a
  // browser that honours it IGNORES `'self'` for scripts, so every top-level
  // `<script>` — Next's bundle tags and the pre-paint theme script alike —
  // must carry the nonce, and webpack's runtime-created chunk scripts are
  // then trusted by propagation. `'self'` is retained for the browsers that
  // do not implement `'strict-dynamic'` and would otherwise fall back to
  // "no scripts at all".
  ["script-src", "'self' 'nonce-{nonce}' 'strict-dynamic'"],
  ["style-src", "'self'"],
  // THE ONE DIRECTIVE C3 DOES NOT CONTAIN, AND THE MEASUREMENT THAT ADDED IT.
  //
  // This is what criterion 1's Report-Only run is FOR, and it is the only
  // thing that run found. Under C3's policy as written, `style-src 'self'`
  // also governs inline `style` ATTRIBUTES — CSP3 falls `style-src-attr` back
  // to `style-src` — and the Report-Only sweep produced exactly three
  // violations across the whole §4 matrix, all of them `style-src-attr` from
  // `components/primitives/Skeleton.tsx:53-56`, which writes each placeholder
  // bar's caller-supplied width and height inline. There is no way to express
  // per-instance geometry without a style attribute: a nonce does not apply
  // to attributes, and moving the geometry into a class would mean deleting
  // `Skeleton`'s `width`/`height` props and rewriting seven call sites across
  // four other work orders' components, from a security PR.
  //
  // So the smallest correction that keeps the shipped UI intact is this one
  // directive, and it is deliberately NOT `style-src 'self' 'unsafe-inline'`:
  // naming `style-src-attr` separately leaves `style-src 'self'` verbatim, so
  // `<style>` elements and stylesheet URLs stay same-origin-only. That
  // narrowing is measured, not assumed — a three-engine probe on this branch
  // confirmed chromium, firefox and webkit all honour `style-src-attr` (the
  // inline attribute applies under this policy and is refused under C3's,
  // in all three), so no engine silently falls back to the wider form.
  //
  // Removing it is a real follow-up, recorded in docs/security.md: it comes
  // free with a `Skeleton` whose geometry is tokenised into classes.
  ["style-src-attr", "'unsafe-inline'"],
  // `data:` is for the inline SVG marks; the app ships no raster images.
  ["img-src", "'self' data:"],
  // WO-02's faces are self-hosted woff2 under `/_next/static/media`.
  ["font-src", "'self'"],
  // C3: "sufficient because SSE is same-origin". The EventSource opens
  // `/api/research/{id}/stream` on the Next origin and the proxy — not the
  // browser — talks to FastAPI.
  ["connect-src", "'self'"],
  ["frame-ancestors", "'none'"],
  ["base-uri", "'none'"],
  ["object-src", "'none'"],
  ["form-action", "'self'"],
];

/**
 * Render the policy for one request.
 *
 * Args:
 *   nonce: The per-request nonce, already base64.
 *
 * Returns:
 *   The header value, directives in C3's order, `; `-separated.
 */
export function buildCspPolicy(nonce: string): string {
  return DIRECTIVES.map(
    ([name, value]) => `${name} ${value.replace("{nonce}", nonce)}`,
  ).join("; ");
}

/** The directive names, in order. Read by the tests and by `docs/security.md`. */
export function cspDirectiveNames(): string[] {
  return DIRECTIVES.map(([name]) => name);
}

/** Which header name a mode writes. `off` writes none. */
export function cspHeaderName(mode: CspMode): string | null {
  if (mode === "enforce") return CSP_HEADER;
  if (mode === "report-only") return CSP_REPORT_ONLY_HEADER;
  return null;
}

/**
 * Decide the mode from the environment.
 *
 * THE DEFAULT IS `enforce`, AND DEVELOPMENT IS THE ONLY EXCEPTION. `next dev`
 * serves its HMR runtime through `eval` and injects its stylesheets as inline
 * `<style>` elements, so this policy would break the dev server outright —
 * and the only honest ways to keep it running are to add `'unsafe-eval'` and
 * `'unsafe-inline'` (which would mean the policy under test is not the policy
 * that ships) or to leave it off there. It is left off there. Every CSP
 * assertion in this repository runs against the production container, which
 * is the artifact the policy actually protects.
 *
 * `CSP_MODE=report-only` is C3's rollout switch: "Ship
 * `Content-Security-Policy-Report-Only` first ... then flip to enforcing".
 * It is an override, never a default, so a deployment that sets nothing
 * enforces.
 *
 * Args:
 *   env: A process environment. Passed in so the test can drive it.
 *
 * Returns:
 *   The mode to apply.
 */
export function cspModeFor(env: Record<string, string | undefined>): CspMode {
  const requested = env[CSP_MODE_ENV];
  if (requested === "report-only" || requested === "enforce" || requested === "off") {
    return requested;
  }
  return env["NODE_ENV"] === "development" ? "off" : "enforce";
}

/**
 * A fresh 128-bit nonce, base64.
 *
 * `crypto.getRandomValues` and `btoa` rather than `node:crypto` and `Buffer`:
 * this runs in the middleware's Edge runtime, where neither Node global
 * exists. 16 bytes is the CSP spec's recommended minimum entropy.
 */
export function createNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/**
 * The nonce `middleware.ts` minted for THIS request, or `undefined`.
 *
 * WHY THE IMPORT IS DYNAMIC AND THE FAILURE IS SWALLOWED. `next/headers` only
 * resolves inside a request scope; `web/tests/tokens.test.ts` and
 * `web/tests/fonts.test.ts` render `RootLayout` through
 * `renderToStaticMarkup` with no request at all, and they are asserting the
 * theme script's position and the font classes, not the CSP. Outside a
 * request there is no nonce to hand out and the correct answer is "none" —
 * the same answer as in development, where `cspModeFor` returns `off` and no
 * script needs one. A nonce that is missing when a policy IS enforcing is not
 * silently tolerable, and it is not silently tolerated: `web/e2e/csp.spec.ts`
 * loads every §4 state under the enforcing header and fails on any blocked
 * script, which is exactly what a dropped nonce would produce.
 */
export async function readCspNonce(): Promise<string | undefined> {
  try {
    const { headers } = await import("next/headers");
    return (await headers()).get(NONCE_HEADER) ?? undefined;
  } catch {
    return undefined;
  }
}
