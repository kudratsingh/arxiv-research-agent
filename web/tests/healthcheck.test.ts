/**
 * WO-30 criteria 6 and 7 — the web container healthcheck.
 *
 * TWO CLAIMS, PULLING IN OPPOSITE DIRECTIONS, AND BOTH ARE THE RULING.
 *
 *   C5 (criterion 6): require HTTP 200 — which is what proves the proxy path
 *   and `API_INTERNAL_BASE` resolve — but **do not** fail on
 *   `status: degraded`, "or a Redis blip would restart the web container for
 *   a backend fault".
 *
 *   H10 (criterion 7): parse `status` **and** `dependencies` anyway, because
 *   "HTTP 200 alone never means healthy" — `/healthz` is always 200 by design
 *   (`src/api/routes.py`, ADR 0042, MUST-KEEP 11).
 *
 * So the probe has to be able to TELL a degraded 200 from a healthy 200 and
 * then deliberately not act on the difference. `distinguishes a degraded 200
 * from a healthy 200` below is criterion 7's test and it asserts both halves
 * in one place — same exit code, different report — because asserting them
 * apart is how one of them quietly inverts.
 *
 * WHY A REAL SERVER AND NOT A MOCKED `http.get`. The probe is what a Docker
 * daemon runs, over a real socket, against a body it did not author. Mocking
 * the transport would leave the two things most likely to break — the URL and
 * the response parsing — untested. `node:http` against a loopback server on
 * an ephemeral port costs milliseconds.
 */

import http from "node:http";
import type { AddressInfo } from "node:net";
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  DEFAULT_URL,
  HEALTHY_STATUS,
  REPORT,
  classify,
  main,
  probe,
} from "@/scripts/healthcheck.mjs";

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const WEB_ROOT = path.resolve(__dirname, "..");
const dockerfile = readFileSync(path.join(WEB_ROOT, "Dockerfile"), "utf8");
const compose = readFileSync(path.join(REPO_ROOT, "docker-compose.yml"), "utf8");

/** `src/api/routes.py`'s healthy body, as `/healthz` really answers it. */
const HEALTHY_BODY = {
  status: "ok",
  active_jobs: 0,
  abandoned_node_threads: 0,
  max_concurrent_jobs: 2,
  dependencies: { redis: "ok", postgres: "ok" },
};

/** The same endpoint during a Redis blip. Still 200 — that is the whole point. */
const DEGRADED_BODY = {
  ...HEALTHY_BODY,
  status: "degraded",
  dependencies: { redis: "error: connection refused", postgres: "ok" },
};

let servers: http.Server[] = [];

afterEach(async () => {
  await Promise.all(
    servers.map((server) => new Promise((resolve) => server.close(resolve))),
  );
  servers = [];
});

/** Serve one canned response on an ephemeral port; return its URL. */
async function serve(
  status: number,
  body: string,
  contentType = "application/json",
): Promise<string> {
  const server = http.createServer((_request, response) => {
    response.writeHead(status, { "content-type": contentType });
    response.end(body);
  });
  servers.push(server);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return `http://127.0.0.1:${port}/api/healthz`;
}

describe("criterion 6 — HTTP 200 is the whole exit-code rule", () => {
  it("exits 0 on a healthy 200", async () => {
    expect(classify(await probe(await serve(200, JSON.stringify(HEALTHY_BODY)))))
      .toMatchObject({ exitCode: 0, report: REPORT.OK, status: "ok" });
  });

  it("exits non-zero on the 503 a misconfigured API_INTERNAL_BASE produces", async () => {
    // `app/api/[...path]/route.ts` answers 503 `api_proxy_misconfigured` when
    // the base is not an HTTP endpoint. 04 §11 item 12 is precisely that a
    // container in this state used to report healthy.
    const url = await serve(503, JSON.stringify({ detail: "api_proxy_misconfigured" }));
    expect(classify(await probe(url)).exitCode).toBe(1);
  });

  it("exits non-zero on the 502 an unreachable upstream produces", async () => {
    const url = await serve(502, JSON.stringify({ detail: "api_upstream_unavailable" }));
    expect(classify(await probe(url)).exitCode).toBe(1);
  });

  it("exits non-zero when nothing answers at all", async () => {
    // Port 1 on loopback: reliably refused, and never a real service.
    const result = classify(await probe("http://127.0.0.1:1/api/healthz", 500));
    expect(result.exitCode).toBe(1);
    expect(result.report).toBe(REPORT.UNREACHABLE);
    // A refused connection is a result, not an exception: a probe that threw
    // would be reported by Docker as an unhealthy container for the right
    // reason and by a human reading the log for the wrong one.
    expect(result.line).toContain("unreachable");
  });

  it("never treats 200 as the only thing it looked at", () => {
    expect(HEALTHY_STATUS).toBe(200);
    expect(DEFAULT_URL).toContain("/api/healthz");
  });
});

describe("criterion 7 — H10, the body is parsed even though it is not fatal", () => {
  it("distinguishes a degraded 200 from a healthy 200, and fails neither", async () => {
    const healthy = classify(await probe(await serve(200, JSON.stringify(HEALTHY_BODY))));
    const degraded = classify(await probe(await serve(200, JSON.stringify(DEGRADED_BODY))));

    // Told apart — H10. `/healthz` is always 200, so a probe that stopped at
    // the status line could not report a dead Redis at all, and this is the
    // only place health is surfaced anywhere in the product.
    expect(healthy.report).toBe(REPORT.OK);
    expect(degraded.report).toBe(REPORT.DEGRADED);
    expect(degraded.status).toBe("degraded");
    expect(degraded.dependencies).toEqual(DEGRADED_BODY.dependencies);
    expect(degraded.line).toContain("connection refused");

    // ...and not acted on — C5. The container keeps serving, because
    // restarting Next does not fix Redis.
    expect(healthy.exitCode).toBe(0);
    expect(degraded.exitCode).toBe(0);
  });

  it("reads `dependencies`, not just `status`", async () => {
    // A body that claims `ok` while a dependency reports otherwise is the
    // case H10's "status AND dependencies" wording exists for.
    const inconsistent = { ...HEALTHY_BODY, dependencies: { redis: "error: timeout" } };
    const result = classify(await probe(await serve(200, JSON.stringify(inconsistent))));
    expect(result.report).toBe(REPORT.DEGRADED);
    expect(result.exitCode).toBe(0);
  });

  it("reports `unknown` for a 200 whose body is not a health document", async () => {
    // Proxied responses can be anything; guessing would be worse than saying
    // so. The exit code still follows the status line, which is all it is
    // allowed to assert.
    const result = classify(await probe(await serve(200, "<html>not json</html>", "text/html")));
    expect(result.report).toBe(REPORT.UNKNOWN);
    expect(result.exitCode).toBe(0);
  });

  it("prints one JSON line and returns the exit code from `main`", async () => {
    const url = await serve(200, JSON.stringify(DEGRADED_BODY));
    const writes: string[] = [];
    const original = process.stdout.write.bind(process.stdout);
    process.stdout.write = ((chunk: unknown) => {
      writes.push(String(chunk));
      return true;
    }) as typeof process.stdout.write;
    try {
      expect(await main(url)).toBe(0);
    } finally {
      process.stdout.write = original;
    }
    expect(writes).toHaveLength(1);
    expect(JSON.parse(writes[0] as string)).toMatchObject({
      event: "web_healthcheck",
      http_status: 200,
      report: "degraded",
    });
  });
});

describe("the probe is what the container actually runs", () => {
  it("is copied into the runtime image and run by the Dockerfile HEALTHCHECK", () => {
    // `output: standalone` traces the server's imports; a file the daemon
    // spawns separately is not one of them, so the COPY is load-bearing.
    expect(dockerfile).toContain("scripts/healthcheck.mjs ./scripts/healthcheck.mjs");
    expect(dockerfile).toContain("CMD node scripts/healthcheck.mjs");
    expect(dockerfile).not.toContain("http://localhost:3000/'");
  });

  it("is what Compose probes too, so the two cannot drift", () => {
    expect(compose).toContain('test: ["CMD", "node", "scripts/healthcheck.mjs"]');
    // The web service gates on the app service being healthy, and `/healthz`
    // is auth-exempt, so this probe keeps passing with API auth on.
    expect(compose).toContain("condition: service_healthy");
  });
});
