/**
 * WO-30 criteria 2 and 3 — the policy, the nonce, and the matcher.
 *
 * WHAT A UNIT TEST CAN AND CANNOT SAY ABOUT A CSP. It can say the header
 * value is exactly the policy that was ratified, that the nonce is fresh per
 * request and long enough to be a nonce, that the rollout switch flips the
 * header NAME rather than the policy, and that the middleware's matcher and
 * `next.config.mjs`'s static header rules describe the same three exclusions
 * so no path falls between them. It cannot say a browser accepts the result —
 * that is `web/e2e/csp.spec.ts`, which loads every §4 state under the real
 * header and fails on any violation. Both halves exist because either alone
 * is a claim rather than a proof: the browser sweep would pass just as
 * happily against a policy somebody quietly widened, and this file would pass
 * just as happily against a policy no browser can satisfy.
 *
 * C3 IS TRANSCRIBED INDEPENDENTLY BELOW. Asserting `buildCspPolicy()` against
 * a constant imported from the module that builds it would assert nothing.
 * `C3_DIRECTIVES` is typed out from 05-MIGRATION.md's sentence, and the one
 * documented addition is asserted as an addition — named, and alone.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  CSP_HEADER,
  CSP_MODE_ENV,
  CSP_REPORT_ONLY_HEADER,
  NONCE_HEADER,
  buildCspPolicy,
  createNonce,
  cspDirectiveNames,
  cspHeaderName,
  cspModeFor,
} from "@/lib/server/csp";

const WEB_ROOT = path.resolve(__dirname, "..");
const middlewareSource = readFileSync(path.join(WEB_ROOT, "middleware.ts"), "utf8");
const nextConfigSource = readFileSync(path.join(WEB_ROOT, "next.config.mjs"), "utf8");

/**
 * 05-MIGRATION.md C3, transcribed by hand:
 *
 *   default-src 'self'; script-src 'self' 'nonce-…' 'strict-dynamic';
 *   style-src 'self'; img-src 'self' data:; font-src 'self';
 *   connect-src 'self'; frame-ancestors 'none'; base-uri 'none';
 *   object-src 'none'; form-action 'self'
 */
const C3_DIRECTIVES: Readonly<Record<string, string>> = {
  "default-src": "'self'",
  "script-src": "'self' 'nonce-{nonce}' 'strict-dynamic'",
  "style-src": "'self'",
  "img-src": "'self' data:",
  "font-src": "'self'",
  "connect-src": "'self'",
  "frame-ancestors": "'none'",
  "base-uri": "'none'",
  "object-src": "'none'",
  "form-action": "'self'",
};

/**
 * The single addition, and the reason it is allowed to exist.
 *
 * Named here rather than folded into the table above so that the diff between
 * "what was ratified" and "what ships" is one line of this test file, and a
 * second addition fails outright.
 */
const DOCUMENTED_ADDITION = "style-src-attr";

/** Split a rendered header value back into directives. */
function parsePolicy(policy: string): Record<string, string> {
  const parsed: Record<string, string> = {};
  for (const part of policy.split(";")) {
    const trimmed = part.trim();
    if (trimmed === "") continue;
    const space = trimmed.indexOf(" ");
    parsed[trimmed.slice(0, space)] = trimmed.slice(space + 1);
  }
  return parsed;
}

describe("criterion 2 — the policy is C3's", () => {
  const rendered = parsePolicy(buildCspPolicy("NONCEVALUE"));

  it.each(Object.entries(C3_DIRECTIVES))(
    "ships `%s` exactly as C3 specifies it",
    (directive, value) => {
      expect(rendered[directive]).toBe(value.replace("{nonce}", "NONCEVALUE"));
    },
  );

  it("adds exactly one directive C3 does not contain, and it is the documented one", () => {
    const added = Object.keys(rendered).filter(
      (directive) => !(directive in C3_DIRECTIVES),
    );
    expect(added).toEqual([DOCUMENTED_ADDITION]);
    // Narrow on purpose: `style-src 'self'` stays verbatim above, so `<style>`
    // elements and stylesheet URLs are still same-origin only. See the comment
    // on the directive in lib/server/csp.ts for the measurement.
    expect(rendered[DOCUMENTED_ADDITION]).toBe("'unsafe-inline'");
  });

  it("drops none of C3's directives", () => {
    for (const directive of Object.keys(C3_DIRECTIVES)) {
      expect(cspDirectiveNames(), `${directive} is missing`).toContain(directive);
    }
  });

  it("never emits `unsafe-eval`, and never widens script-src", () => {
    const policy = buildCspPolicy(createNonce());
    expect(policy).not.toContain("'unsafe-eval'");
    // The one `'unsafe-inline'` in the policy is style-src-attr's. If it ever
    // appears inside script-src, `'strict-dynamic'` would ignore it in a
    // modern browser and an old one would execute anything — the worst of
    // both, and exactly the drift this asserts against.
    expect(parsePolicy(policy)["script-src"]).not.toContain("'unsafe-inline'");
    expect(policy.match(/'unsafe-inline'/g)).toHaveLength(1);
  });

  it("puts the nonce in script-src and nowhere else", () => {
    const nonce = createNonce();
    const policy = buildCspPolicy(nonce);
    expect(policy).toContain(`'nonce-${nonce}'`);
    expect(policy.match(new RegExp(`'nonce-`, "g"))).toHaveLength(1);
  });
});

describe("criterion 1 — Report-Only first, then enforcing, from one build", () => {
  it("switches the header NAME, never the policy", () => {
    // The two runs criterion 1 requires have to be the same policy observed
    // two ways. If the report-only run used a different (weaker) policy, its
    // zero-violation result would say nothing about the enforcing run.
    expect(buildCspPolicy("N")).toBe(buildCspPolicy("N"));
    expect(cspHeaderName("enforce")).toBe(CSP_HEADER);
    expect(cspHeaderName("report-only")).toBe(CSP_REPORT_ONLY_HEADER);
    expect(cspHeaderName("off")).toBeNull();
  });

  it("enforces by default, so an unconfigured deployment is not the weak one", () => {
    expect(cspModeFor({})).toBe("enforce");
    expect(cspModeFor({ NODE_ENV: "production" })).toBe("enforce");
    expect(cspModeFor({ NODE_ENV: "test" })).toBe("enforce");
  });

  it("honours the rollout override in both directions", () => {
    expect(cspModeFor({ [CSP_MODE_ENV]: "report-only" })).toBe("report-only");
    expect(cspModeFor({ [CSP_MODE_ENV]: "enforce", NODE_ENV: "development" })).toBe(
      "enforce",
    );
    expect(cspModeFor({ [CSP_MODE_ENV]: "off" })).toBe("off");
  });

  it("ignores a value it does not recognise rather than guessing", () => {
    // A typo'd `CSP_MODE=reportonly` must not silently disable the policy.
    expect(cspModeFor({ [CSP_MODE_ENV]: "reportonly" })).toBe("enforce");
    expect(cspModeFor({ [CSP_MODE_ENV]: "" })).toBe("enforce");
  });

  it("is off in development only, and says why in the source", () => {
    expect(cspModeFor({ NODE_ENV: "development" })).toBe("off");
    // `next dev` serves HMR through eval and injects <style> elements, so the
    // only alternatives were 'unsafe-eval' + 'unsafe-inline' in the shipped
    // policy or no policy on the dev server. The second was chosen; every CSP
    // assertion runs against the production container.
    const source = readFileSync(
      path.join(WEB_ROOT, "lib", "server", "csp.ts"),
      "utf8",
    );
    expect(source).toContain("eval");
  });
});

describe("the nonce", () => {
  it("is fresh on every call", () => {
    const seen = new Set(Array.from({ length: 64 }, () => createNonce()));
    expect(seen.size).toBe(64);
  });

  it("carries 128 bits, base64, with no character that would break the header", () => {
    const nonce = createNonce();
    // 16 bytes -> 24 base64 characters including padding.
    expect(nonce).toHaveLength(24);
    expect(nonce).toMatch(/^[A-Za-z0-9+/]+={0,2}$/);
    expect(nonce).not.toContain(";");
    expect(nonce).not.toContain("'");
  });
});

describe("criterion 3 — RC-07's matcher, and the paths it hands to next.config", () => {
  it("excludes exactly the three paths RC-07 names", () => {
    // RC-07: "a `matcher` that excludes `/api/*`, `/_next/static/*`, and the
    // icon, so proxy and asset traffic take no extra hop".
    // `String.raw` because the assertion is about the FILE's text, where the
    // TypeScript string literal's escape is itself two characters.
    expect(middlewareSource).toContain(String.raw`(?!api/|_next/static/|icon\\.svg)`);
  });

  it("covers every other path, so no document is served without a policy", () => {
    const matcher = /matcher: \["([^"]+)"\]/.exec(middlewareSource);
    expect(matcher, "middleware.ts has no single-entry matcher").not.toBeNull();
    const pattern = new RegExp(
      `^${(matcher as RegExpExecArray)[1] as string}$`.replace(/\\\\/g, "\\"),
    );
    for (const covered of ["/", "/c/abc", "/c/abc?job=x", "/nope", "/_next/image"]) {
      expect(pattern.test(covered), `${covered} is not matched`).toBe(true);
    }
    for (const excluded of [
      "/api/healthz",
      "/api/research/abc/stream",
      "/_next/static/chunks/main.js",
      "/icon.svg",
    ]) {
      expect(pattern.test(excluded), `${excluded} should be excluded`).toBe(false);
    }
  });

  it("hands those three paths to next.config.mjs, so the gap is covered not created", () => {
    // The middleware skipping a path is only safe because something else sets
    // a header on it. These two files are the two halves of one decision.
    expect(nextConfigSource).toContain('source: "/api/:path*"');
    expect(nextConfigSource).toContain('source: "/_next/static/:path*"');
    expect(nextConfigSource).toContain('source: "/icon.svg"');
    expect(nextConfigSource).toContain("default-src 'none'");
    expect(nextConfigSource).toContain("X-Content-Type-Options");
  });

  it("passes the nonce to the renderer as well as to the layout", () => {
    // Next stamps its own <script> tags only when it finds the CSP on the
    // REQUEST headers, so setting it on the response alone would leave every
    // bundle chunk un-nonced and refused under 'strict-dynamic'.
    expect(middlewareSource).toContain("requestHeaders.set(headerName, policy)");
    expect(middlewareSource).toContain(`requestHeaders.set(NONCE_HEADER, nonce)`);
    expect(NONCE_HEADER).toBe("x-nonce");
  });
});
