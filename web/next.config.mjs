/**
 * WO-30 added the static half of the security headers here.
 *
 * `web/middleware.ts` owns the per-request, nonce-carrying CSP on every
 * document route, and RC-07's condition for creating that file at all was a
 * `matcher` excluding `/api/*`, `/_next/static/*` and the icon so proxy and
 * asset traffic take no extra hop. Excluding them from the middleware would
 * otherwise leave three paths with no policy at all — and one of them,
 * `/icon.svg`, is an SVG, which is a scriptable document the moment a browser
 * navigates straight to it.
 *
 * So the excluded three get a policy from here instead: static, nonce-free,
 * and set by the server without a middleware invocation. It is deliberately
 * stricter than the document policy rather than a copy of it, because none of
 * these responses is ever a page: nothing should load, and nothing should be
 * loadable from them.
 *
 * `web/tests/csp.test.ts` asserts that the sources listed here and the
 * middleware's matcher describe the same three exclusions, so the two halves
 * cannot drift into a gap.
 */

/** Nothing loads, nothing frames, nothing submits. */
const INERT_CSP =
  "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'";

const INERT_HEADERS = [
  { key: "Content-Security-Policy", value: INERT_CSP },
  // The proxy streams a body it did not author. `nosniff` is what stops a
  // browser deciding for itself that an upstream `text/plain` is really HTML.
  { key: "X-Content-Type-Options", value: "nosniff" },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  // `standalone` bundles a minimal server + node_modules subset into
  // `.next/standalone/`, which is what the Dockerfile's runtime stage
  // copies. Cuts the runtime image size by roughly 5x versus a full
  // `next start` install.
  output: "standalone",
  reactStrictMode: true,
  // Browser API calls stay same-origin under `/api`. The catch-all
  // route handler resolves API_INTERNAL_BASE at runtime and injects
  // ARXIV_API_KEY server-side, including for SSE and exports.
  async headers() {
    return [
      { source: "/api/:path*", headers: INERT_HEADERS },
      { source: "/_next/static/:path*", headers: INERT_HEADERS },
      { source: "/icon.svg", headers: INERT_HEADERS },
    ];
  },
};

export default nextConfig;
