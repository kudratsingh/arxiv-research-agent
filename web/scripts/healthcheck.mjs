#!/usr/bin/env node
/**
 * The web container's healthcheck (WO-30, 05-MIGRATION.md C5,
 * 04-ARCHITECTURE.md §11 item 12, H10).
 *
 * WHAT WAS WRONG WITH THE OLD ONE. It probed Next `/` and nothing else
 * (`web/Dockerfile`, `docker-compose.yml`), so a container with a
 * misconfigured `API_INTERNAL_BASE` reported *healthy* while serving an app
 * whose every request 503s. 04 §11 item 12 is that finding; C5 is the fix:
 * probe `/api/healthz`, which only answers 200 when the proxy resolved its
 * upstream and FastAPI answered — a bad base gives 503 and an unreachable
 * upstream gives 502, both from `app/api/[...path]/route.ts`.
 *
 * WHY A 200 IS THE WHOLE EXIT-CODE RULE, AND `degraded` IS NOT.
 * `/healthz` is always 200 by design (`src/api/routes.py`, ADR 0042): it
 * answers "is this process alive", and restarting the process does not fix a
 * dead Redis. C5 is explicit — "**do not** fail on `status: degraded`, or a
 * Redis blip would restart the web container for a backend fault". The blast
 * radius of getting this backwards is a rolling-restart storm across a
 * healthy web tier during a backend incident, which is why the rule is
 * stated once, here, and asserted in `web/tests/healthcheck.test.ts`.
 *
 * WHY THE BODY IS PARSED ANYWAY — H10. "HTTP 200 alone never means healthy"
 * (04 §9.1 H10, MUST-KEEP 11). A probe that only looked at the status line
 * would be unable to tell a healthy deployment from one running on a dead
 * Redis, and this is the ONLY place health is surfaced at all — no product UI
 * consumes `/healthz`. So the body's `status` and `dependencies` are parsed
 * and printed on every probe: `docker inspect --format '{{json .State.Health}}'`
 * keeps the last five outputs, which makes "when did Redis go" answerable
 * from the container alone. Printed, and never fatal.
 *
 * NO DEPENDENCIES AND NO IMPORTS FROM `web/`. It runs inside the runtime
 * image, which contains only `.next/standalone` plus this file — see the
 * `COPY` in `web/Dockerfile`. `node:http` and nothing else.
 */

import http from "node:http";
import { pathToFileURL } from "node:url";

/** Where the probe goes. Overridable so the test can point it at a stub. */
export const DEFAULT_URL = "http://127.0.0.1:3000/api/healthz";

/** Compose gives the probe 3s; stay inside it so a timeout is ours, not theirs. */
export const DEFAULT_TIMEOUT_MS = 2500;

/** The only status that means "this container is serving". */
export const HEALTHY_STATUS = 200;

/**
 * What the probe concluded, before any exit code is chosen.
 *
 * `ok` and `degraded` are the two values `HealthResponse.status` takes
 * (`src/api/schemas.py`); `unknown` covers a 200 whose body was not the
 * document we expected, which is a real possibility for a proxied response
 * and is reported rather than guessed at.
 */
export const REPORT = {
  OK: "ok",
  DEGRADED: "degraded",
  UNKNOWN: "unknown",
  UNREACHABLE: "unreachable",
};

/**
 * Turn one probe result into the line the container logs and the exit code.
 *
 * Args:
 *   result: `{ statusCode, body }` from the request, or `{ error }`.
 *
 * Returns:
 *   `{ exitCode, report, status, dependencies, line }`. `exitCode` is 0 if
 *   and only if the HTTP status was 200 — `report` may still be `degraded`,
 *   and that is the whole point of C5.
 */
export function classify(result) {
  if (result.error !== undefined || result.statusCode === undefined) {
    return {
      exitCode: 1,
      report: REPORT.UNREACHABLE,
      status: null,
      dependencies: {},
      line: JSON.stringify({
        event: "web_healthcheck",
        report: REPORT.UNREACHABLE,
        error: String(result.error ?? "no response"),
      }),
    };
  }

  const healthy = result.statusCode === HEALTHY_STATUS;

  let status = null;
  let dependencies = {};
  let report = REPORT.UNKNOWN;
  try {
    const parsed = JSON.parse(result.body ?? "");
    if (parsed !== null && typeof parsed === "object") {
      status = typeof parsed.status === "string" ? parsed.status : null;
      dependencies =
        parsed.dependencies !== null && typeof parsed.dependencies === "object"
          ? parsed.dependencies
          : {};
      // H10: the two fields together, not the status line. `ok` requires the
      // word AND that no dependency reported anything other than `ok`.
      const dependencyValues = Object.values(dependencies);
      const allDependenciesUp = dependencyValues.every((value) => value === "ok");
      if (status === "ok" && allDependenciesUp) report = REPORT.OK;
      else if (status !== null) report = REPORT.DEGRADED;
    }
  } catch {
    // A 200 with an unparseable body is `unknown`, not a failure: the
    // container is serving and the proxy reached its upstream, which is
    // exactly what the exit code is allowed to assert.
  }

  return {
    exitCode: healthy ? 0 : 1,
    report,
    status,
    dependencies,
    line: JSON.stringify({
      event: "web_healthcheck",
      http_status: result.statusCode,
      report,
      status,
      dependencies,
    }),
  };
}

/**
 * Perform the probe.
 *
 * Args:
 *   url: Absolute URL to GET.
 *   timeoutMs: Abort after this long.
 *
 * Returns:
 *   A promise of `{ statusCode, body }` or `{ error }`. It never rejects —
 *   an unreachable upstream is a result, not an exception.
 */
export function probe(url = DEFAULT_URL, timeoutMs = DEFAULT_TIMEOUT_MS) {
  return new Promise((resolve) => {
    const request = http.get(url, (response) => {
      let body = "";
      response.setEncoding("utf8");
      // Bounded: `/healthz` is a small object, and a probe is not a place to
      // accumulate an unbounded string from a misbehaving upstream.
      response.on("data", (chunk) => {
        if (body.length < 8192) body += chunk;
      });
      response.on("end", () => resolve({ statusCode: response.statusCode, body }));
    });
    request.setTimeout(timeoutMs, () => {
      request.destroy(new Error(`timed out after ${timeoutMs}ms`));
    });
    request.on("error", (error) => resolve({ error: error.message }));
  });
}

/** Probe, print the one-line report, exit 0 on HTTP 200 and 1 otherwise. */
export async function main(url = process.env.HEALTHCHECK_URL ?? DEFAULT_URL) {
  const outcome = classify(await probe(url));
  process.stdout.write(`${outcome.line}\n`);
  return outcome.exitCode;
}

// Executed rather than imported: run it. Same guard as `audit-gate.mjs` and
// `route-budgets.mjs`, so it is false under Vitest, which imports the module.
if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main().then((code) => {
    process.exit(code);
  });
}
