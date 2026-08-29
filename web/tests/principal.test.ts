/**
 * WO-30 criteria 8 and 9 — the two MT-01 seams that are actually built, and
 * the one that is deliberately only reserved.
 *
 * S1 IS A NO-OP AND THAT IS THE ACCEPTANCE CRITERION. 04-ARCHITECTURE.md §10
 * asks for `resolveUpstreamPrincipal(request)` to be extracted, with "the
 * shared-principal implementation returns the env key unchanged, so
 * extracting the function is a **no-op refactor** today". The proof of the
 * no-op is not in this file — it is `web/tests/apiProxyRoute.test.ts` still
 * passing **unmodified** (criterion 5 / RC-08), which is the assertion the
 * card tells reviewers to treat as the gate. What this file adds is the part
 * that test cannot see: that the function's own behaviour matches the seam's
 * specified shape, and that the boundary it belongs to has not been widened.
 *
 * S2 IS A DIRECTORY THAT MUST NOT EXIST. §10: "Document `/api/auth/*` as
 * **reserved** ... Nothing is added now." A reservation nobody checks is a
 * sentence in a document, so the absence is asserted here and the reservation
 * itself is written down in `docs/security.md`.
 */

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  SHARED_PRINCIPAL_KEY_ID,
  resolveUpstreamPrincipal,
} from "@/lib/server/principal";

const WEB_ROOT = path.resolve(__dirname, "..");
const originalApiKey = process.env.ARXIV_API_KEY;

afterEach(() => {
  if (originalApiKey === undefined) delete process.env.ARXIV_API_KEY;
  else process.env.ARXIV_API_KEY = originalApiKey;
});

const anyRequest = (): Request => new Request("http://web.local/api/healthz");

describe("S1 — credential resolution, extracted and unchanged", () => {
  it("returns the env key unchanged, under the shared principal", async () => {
    process.env.ARXIV_API_KEY = "server-only-secret";
    await expect(resolveUpstreamPrincipal(anyRequest())).resolves.toEqual({
      keyId: SHARED_PRINCIPAL_KEY_ID,
      apiKey: "server-only-secret",
    });
  });

  it("returns null in the auth-off configuration, so no header is sent", async () => {
    // `docker-compose.yml` defaults `WEB_API_KEY` to empty and
    // `ENABLE_API_AUTH` to false: the zero-config demo. An empty `X-API-Key`
    // header is not the same thing as no header, and the backend would treat
    // it as a failed authentication rather than as an unauthenticated call.
    delete process.env.ARXIV_API_KEY;
    await expect(resolveUpstreamPrincipal(anyRequest())).resolves.toBeNull();
    process.env.ARXIV_API_KEY = "";
    await expect(resolveUpstreamPrincipal(anyRequest())).resolves.toBeNull();
  });

  it("resolves the same principal for every request — D-009, no faked identity", async () => {
    process.env.ARXIV_API_KEY = "server-only-secret";
    // Two requests a session-aware implementation would tell apart. Today
    // they must not be told apart: the revamp "must not fake login or
    // per-user views", and a seam that quietly varied by cookie would be
    // exactly that.
    const withCookie = new Request("http://web.local/api/conversations", {
      headers: { cookie: "session=someone" },
    });
    const withAuth = new Request("http://web.local/api/conversations", {
      headers: { authorization: "Bearer someone-else" },
    });
    const a = await resolveUpstreamPrincipal(withCookie);
    const b = await resolveUpstreamPrincipal(withAuth);
    expect(a).toEqual(b);
    expect(a?.keyId).toBe("shared");
  });

  it("is the only module that reads ARXIV_API_KEY", () => {
    // 04 §1.3 constraint 1: the route handler remains the SOLE credential
    // boundary, and after this extraction the key itself is read in exactly
    // one place. A second reader would be a second credential path — the
    // thing that constraint says needs its own ADR.
    const readers = walk(WEB_ROOT).filter((file) =>
      code(file).includes("process.env.ARXIV_API_KEY"),
    );
    expect(readers.map((file) => path.relative(WEB_ROOT, file)).sort()).toEqual([
      "lib/server/principal.ts",
    ]);
  });

  it("is imported only by the proxy route, never by anything a browser loads", () => {
    const importers = walk(WEB_ROOT).filter((file) =>
      /from "@\/lib\/server\/principal"/.test(code(file)),
    );
    expect(importers.map((file) => path.relative(WEB_ROOT, file)).sort()).toEqual([
      "app/api/[...path]/route.ts",
    ]);
  });
});

describe("S2 — `/api/auth/*` is reserved, and nothing implements it", () => {
  it("has no route file, so the catch-all still owns the path", () => {
    // In the App Router a more specific segment takes precedence over a
    // catch-all, which is what makes the reservation cost nothing now and
    // work later. Until MT-01 lands, `/api/auth/login` is forwarded upstream
    // and 404s — the correct answer for a product with no login.
    expect(existsSync(path.join(WEB_ROOT, "app", "api", "auth"))).toBe(false);
  });

  it("is written down where an operator would look", () => {
    const security = readFileSync(
      path.join(WEB_ROOT, "..", "docs", "security.md"),
      "utf8",
    );
    expect(security).toContain("/api/auth/*");
    expect(security).toContain("reserved");
  });
});

describe("criterion 10 — CSRF is named as unaddressed, not quietly implied", () => {
  it("docs/security.md says so in as many words", () => {
    const security = readFileSync(
      path.join(WEB_ROOT, "..", "docs", "security.md"),
      "utf8",
    );
    // The card is explicit that "proxy hardened" must never be read as "CSRF
    // considered". This is the assertion that keeps the sentence in the file.
    expect(security).toMatch(/CSRF/);
    expect(security).toMatch(/out of scope/i);
    expect(security).toMatch(/MT-01/);
  });
});

/**
 * A file's source with its comments removed.
 *
 * The two scans above are about what the code DOES. `route.ts`'s header
 * comment quotes `process.env.ARXIV_API_KEY` while explaining that the read
 * moved out of it, and a scan that counted the sentence would force the
 * explanation to be deleted to keep the test green — which is the wrong way
 * round.
 */
function code(file: string): string {
  return readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

/**
 * Every shipped source file: `app/`, `components/`, `lib/`, and the one
 * top-level module.
 *
 * SHIPPED CODE ONLY, DELIBERATELY. `tests/` names `ARXIV_API_KEY` in three
 * places — including the frozen `apiProxyRoute.test.ts`, which must be able
 * to set it — and a scan that counted those would have to be loosened until
 * it stopped meaning anything. The claim being tested is about the product,
 * not about its harness.
 */
function walk(root: string): string[] {
  const found: string[] = [path.join(root, "middleware.ts")];
  const visit = (dir: string): void => {
    for (const entry of readdirSync(dir)) {
      const full = path.join(dir, entry);
      if (statSync(full).isDirectory()) visit(full);
      else if (/\.(ts|tsx)$/.test(entry) && !/\.stories\.tsx$/.test(entry)) {
        found.push(full);
      }
    }
  };
  for (const dir of ["app", "components", "lib"]) visit(path.join(root, dir));
  return found;
}
