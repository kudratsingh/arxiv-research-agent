/**
 * The mock-mode precondition for the pass-through session routes (WO-W13b).
 *
 * WHY THIS FILE EXISTS. `support/paid-path.ts` fulfils every paid write in
 * the browser, which is the right posture for `POST /api/research` and
 * `POST /api/conversations` and is the wrong posture for exactly one test:
 * the end-to-end guided-read run Gate W1 row 1 asks for. A session create
 * and a session turn that never reach the backend cannot start a graph, and
 * a graph that never runs cannot park on `awaiting_learner`, write a
 * checkpoint, or be resumed after a reload. So those two routes get a
 * **mock-mode pass-through**: still counted, still recorded, but forwarded.
 *
 * FORWARDING IS ONLY SAFE UNDER ONE PRECONDITION, AND IT IS ASSERTED RATHER
 * THAN ASSUMED. Under `USE_MOCK_DATA=true` the session graph makes **no
 * model call at all** — `check_in_agent` takes `_fallback_plan`
 * (`src/agents/tutor.py:159`), `_tutor_prompts` returns two constants
 * (`:248`), and the assessment agent takes its own mock branch
 * (`src/agents/assessment.py:178`). Zero paid calls by construction, not by
 * a key that happens to be invalid. `ANTHROPIC_API_KEY=local-preview-disabled`
 * is the second, independent boundary and is asserted here too — "it would
 * have failed anyway" is a coincidence, not a cost boundary, and the whole
 * point of this file is that the pass-through does not rest on one.
 *
 * WHAT IS CHECKED, IN TWO PLACES, AND WHY BOTH.
 *
 *   1. **The overlay's pinned env.** `support/compose.e2e.yml` is the file a
 *      reviewer edits and the file CI brings the stack up from, so it is the
 *      declaration of intent. Parsing it catches the regression that matters
 *      most — somebody deletes the pin — at the moment it happens, on every
 *      machine, with no daemon required.
 *   2. **The container that is actually running.** A pin in a file proves
 *      nothing about a stack somebody started before the pin existed, or
 *      about an `E2E_BASE_URL` pointing somewhere else entirely. When
 *      `docker inspect` can reach the app container its environment is
 *      checked too, and a disagreement is a hard failure.
 *
 * When the daemon is not reachable the runtime half reports **unverified**
 * rather than passing quietly: the caller prints the summary, so a run whose
 * only evidence is the file pin says so in its own output.
 *
 * WHAT THIS FILE DOES NOT CLAIM. It is a precondition, not the proof. The
 * proof that the run spent nothing is `llm_calls` on the finished session,
 * read back from the API in `session-flow.spec.ts`, plus the unchanged
 * `POST /api/research = 0` line in `research-post-count.txt`.
 */

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { DISABLED_API_KEY } from "./env";

/**
 * The overlay this tier brings the stack up from.
 *
 * `__dirname`, not `import.meta.url`: Playwright transpiles specs and their
 * support modules to CommonJS, where `import.meta` is a syntax error — the
 * whole suite refuses to load. `web/tests/support/copyGraph.ts` resolves
 * `WEB_ROOT` the same way for the same reason.
 */
export const OVERLAY_PATH = join(__dirname, "compose.e2e.yml");

/**
 * The `app` environment the pass-through requires, as `KEY: value`.
 *
 * Both entries are load-bearing and both are argued in the header above.
 * They are declared here rather than inline so the assertion, the failure
 * message and the documentation cannot drift apart.
 */
export const REQUIRED_APP_ENV: Readonly<Record<string, string>> = {
  USE_MOCK_DATA: "true",
  ANTHROPIC_API_KEY: DISABLED_API_KEY,
};

/** The app container's name, the same variable `compose.e2e.yml` reads. */
export const APP_CONTAINER = process.env.E2E_APP_CONTAINER ?? "arxiv-wo21-app";

/**
 * Read `services.app.environment` out of the overlay.
 *
 * A hand-rolled reader rather than a YAML dependency: the block is a flat
 * `KEY: value` map at a known indentation, this tier ships no YAML parser
 * today, and adding one to read six lines would put a dependency into
 * `package.json` for a test-support file. The reader is deliberately strict —
 * it returns only what it can prove it read, so a restructured overlay
 * produces "the pin is missing" (which is investigable) rather than a
 * silently empty map that would pass.
 */
export function readOverlayAppEnv(path: string = OVERLAY_PATH): Record<string, string> {
  const lines = readFileSync(path, "utf8").split("\n");
  const env: Record<string, string> = {};
  let inApp = false;
  let inEnv = false;
  for (const line of lines) {
    if (/^\s{2}\S/.test(line)) {
      // A service key: `  app:`, `  web:`, …
      inApp = /^\s{2}app:\s*$/.test(line);
      inEnv = false;
      continue;
    }
    if (inApp && /^\s{4}\S/.test(line)) {
      inEnv = /^\s{4}environment:\s*$/.test(line);
      continue;
    }
    if (!inApp || !inEnv) continue;
    const match = /^\s{6}([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$/.exec(line);
    if (match === null) continue;
    const [, key, rawValue] = match;
    if (key === undefined || rawValue === undefined) continue;
    env[key] = rawValue.replace(/^["']|["']$/g, "");
  }
  return env;
}

/**
 * The running container's environment, or `null` when it cannot be read.
 *
 * `null` is not a pass. The caller reports it as `runtime=unverified`, which
 * is the honest description of a check that did not run.
 */
export function readContainerEnv(container: string = APP_CONTAINER): Record<string, string> | null {
  let raw: string;
  try {
    raw = execFileSync(
      "docker",
      ["inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", container],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: 15_000 },
    );
  } catch {
    return null;
  }
  const env: Record<string, string> = {};
  for (const line of raw.split("\n")) {
    const index = line.indexOf("=");
    if (index <= 0) continue;
    env[line.slice(0, index)] = line.slice(index + 1);
  }
  return env;
}

function mismatches(
  env: Record<string, string>,
  source: string,
): string[] {
  return Object.entries(REQUIRED_APP_ENV)
    .filter(([key, want]) => env[key] !== want)
    .map(([key, want]) => `${source}: ${key} is ${env[key] ?? "unset"}, must be ${want}`);
}

/**
 * Refuse to forward a session write to a stack that is not in mock mode.
 *
 * Throws — loudly, with the fix — rather than skipping. A skipped
 * cost-boundary check reads as green in a summary, and this one gates the
 * only two routes in the suite that reach a graph.
 *
 * @returns a one-line summary the caller prints and records, so the check is
 *   visible in the run output rather than only in its absence of failure.
 */
export function assertMockModeStack(): string {
  const overlay = readOverlayAppEnv();
  const problems = mismatches(overlay, `${OVERLAY_PATH}#services.app.environment`);

  const container = readContainerEnv();
  if (container !== null) {
    problems.push(...mismatches(container, `container ${APP_CONTAINER}`));
  }

  if (problems.length > 0) {
    throw new Error(
      [
        "refusing to forward a guided-session write: the stack is not in mock mode.",
        ...problems.map((problem) => `  - ${problem}`),
        "",
        "The two session routes are forwarded to the backend ONLY under",
        `USE_MOCK_DATA=true (no model call is constructed at all) with`,
        `ANTHROPIC_API_KEY=${DISABLED_API_KEY}. Pin both on the app service in`,
        `${OVERLAY_PATH} and re-run 'npm run e2e:stack:up'.`,
      ].join("\n"),
    );
  }

  return [
    "[mock-mode] guided-session pass-through armed:",
    `overlay=${OVERLAY_PATH.split("/").slice(-3).join("/")}`,
    `USE_MOCK_DATA=${overlay.USE_MOCK_DATA}`,
    `ANTHROPIC_API_KEY=${overlay.ANTHROPIC_API_KEY}`,
    container === null
      ? `runtime=unverified (docker inspect ${APP_CONTAINER} unavailable)`
      : `runtime=verified (${APP_CONTAINER})`,
  ].join(" ");
}
