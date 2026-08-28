/**
 * Minimal FastAPI stand-in for the `web-image` CI smoke (WO-25 / 05-MIGRATION C1).
 *
 * The web image's proxy (`web/app/api/[...path]/route.ts`) forwards
 * `/api/<segments>` to `API_INTERNAL_BASE/<segments>`, returning the upstream
 * status verbatim (503 on a bad base, 502 when the upstream is unreachable).
 * So a 200 on `/api/healthz` through the container proves the whole proxy path
 * resolved — this stub only has to answer `GET /healthz` the way
 * `src/api/routes.py::healthz` does: always 200, dependency state in the body.
 *
 * `/research` is refused, never emulated. The cost boundary in
 * `docs/revamp/06-WORK-ORDERS.md` §0 is that no automated tier ever runs a
 * research job, so a stub that answered `POST /research` with a plausible
 * `job_id` would let a future smoke test go green on a call that must not
 * exist. Plain node, no dependencies: this runs on the CI runner, not in the image.
 *
 * Usage: `node web/e2e/support/stub-upstream.mjs` (STUB_PORT/STUB_HOST override).
 */
import { createServer } from "node:http";

const PORT = Number(process.env.STUB_PORT ?? 8000);
const HOST = process.env.STUB_HOST ?? "0.0.0.0";

/** Shape of `HealthResponse` in src/api/routes.py; empty deps = not degraded. */
const HEALTHZ = {
  status: "ok",
  active_jobs: 0,
  abandoned_node_threads: 0,
  max_concurrent_jobs: 2,
  dependencies: {},
};

/** Write a JSON body with an explicit length so the proxy can stream it. */
function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
  });
  res.end(body);
}

const server = createServer((req, res) => {
  const { pathname } = new URL(req.url ?? "/", "http://stub-upstream.invalid");
  console.log(`stub-upstream <- ${req.method} ${pathname}`);
  req.resume(); // drain any request body; nothing here reads one

  if (pathname === "/research" || pathname.startsWith("/research/")) {
    sendJson(res, 501, {
      detail:
        "stub_refuses_research: POST /research is never exercised by an " +
        "automated tier (06-WORK-ORDERS.md §0, cost boundary)",
    });
  } else if (req.method === "GET" && pathname === "/healthz") {
    sendJson(res, 200, HEALTHZ);
  } else {
    sendJson(res, 404, { detail: `stub_unhandled: ${req.method} ${pathname}` });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`stub-upstream listening on http://${HOST}:${PORT}`);
});
