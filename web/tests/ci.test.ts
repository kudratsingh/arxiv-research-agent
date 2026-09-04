/**
 * WO-24 — the CI wiring, asserted against `.github/workflows/ci.yml` itself.
 *
 * A workflow file is the one part of this repository that no other test can
 * reach: it does not import, it is not built, and it only runs where a failure
 * is expensive to discover. Two classes of claim are pinned here.
 *
 *   1. **B4 — the build tool stays pinned** (05-MIGRATION.md §3.1). The
 *      migration says `web/package.json` uses `next build --webpack` and that
 *      Turbopack is a separate ADR (R-15). Without an assertion that is a
 *      sentence, not a gate: a one-word edit would silently change what the
 *      production build, the Docker image and the route-budget measurement are
 *      all produced by. WO-24 criterion 6 asks for exactly this.
 *
 *   2. **The cost boundary in CI** (06-WORK-ORDERS.md §0). `web-e2e` brings up
 *      the real stack, so the one thing that must never drift is the API key
 *      it hands it. The sentinel is asserted present and the repository secret
 *      asserted absent — from the whole file, not just that job.
 *
 *   3. **The Python tiers and the check count** (WO-A13). Five tiers and two
 *      coverage floors gate a merge as *steps inside one job*, which is a
 *      decision that is invisible in a diff and easy to undo by helpfully
 *      splitting them out. The assertions below pin the shape: nine jobs, the
 *      floors read from the Makefile rather than restated here, and each tier
 *      present by the command that runs it.
 *
 * WHY TEXT AND NOT A PARSED DOCUMENT. There is no YAML parser in this
 * package's dependencies, and adding one so a test can read a file that
 * changes a few times a year would be the wrong trade (js-yaml exists in
 * node_modules only as somebody else's transitive dependency, which is not a
 * thing to build a gate on). Every assertion below is deliberately about a
 * *literal* that must or must not appear — which is what the two claims above
 * actually are.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const WEB_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..");
const WORKFLOW_PATH = path.join(REPO_ROOT, ".github", "workflows", "ci.yml");

const workflow = readFileSync(WORKFLOW_PATH, "utf8");
const packageJson = JSON.parse(readFileSync(path.join(WEB_ROOT, "package.json"), "utf8")) as {
  scripts: Record<string, string>;
};

describe("B4 — the build tool stays pinned to webpack", () => {
  it("`build` is exactly `next build --webpack`", () => {
    // Exactly. Not "contains webpack": `next build --webpack --turbopack` and
    // `next build` both contain fewer surprises than they look like they do.
    expect(packageJson.scripts["build"]).toBe("next build --webpack");
  });

  it("no script anywhere opts into Turbopack", () => {
    // R-15 is a separate ADR. `next dev` defaults to webpack in this repo too,
    // and a `--turbo`/`--turbopack` in any script would mean the thing being
    // tested locally is not the thing being built.
    for (const [name, command] of Object.entries(packageJson.scripts)) {
      expect(command, `scripts.${name} opts into Turbopack`).not.toMatch(/--turbo/);
    }
  });

  it("the production image and the budget check both build through that one script", () => {
    // web/Dockerfile runs `npm run build`, and `npm run budgets` is
    // `npm run build && node scripts/route-budgets.mjs`. So the pin above is
    // the single definition of how this app is compiled — the container, the
    // CI build and the measured bundle cannot diverge from each other.
    expect(readFileSync(path.join(WEB_ROOT, "Dockerfile"), "utf8")).toContain("RUN npm run build");
    expect(packageJson.scripts["budgets"]).toBe(
      "npm run build && node scripts/route-budgets.mjs",
    );
  });
});

describe("the cost boundary holds in CI", () => {
  it("hands the e2e stack the disabled sentinel, hard-coded", () => {
    expect(workflow).toContain("ANTHROPIC_API_KEY: local-preview-disabled");
  });

  it("never gives any job the repository's Anthropic secret", () => {
    // The secret exists — `eval-nightly.yml` is the only workflow allowed to
    // spend it. A `${{ secrets.ANTHROPIC_API_KEY }}` appearing in this file
    // would put a real key in front of a browser tier whose whole design
    // assumes it cannot have one.
    expect(workflow).not.toMatch(/secrets\.ANTHROPIC_API_KEY/);
    expect(workflow).not.toMatch(/ANTHROPIC_API_KEY:\s*\$\{\{/);
  });

  it("only ever takes the stack down through stack.sh", () => {
    // A bare `docker compose down` resolves the project from the working
    // directory and the base file's hardcoded container names, and removes
    // whatever else is running under them (06-WORK-ORDERS.md §5.4).
    expect(workflow).not.toMatch(/docker compose[^\n]*\bdown\b/);
  });
});

describe("the Python tiers are wired (WO-A13)", () => {
  /**
   * Everything WO-A13 added lives in one job, so every assertion here reads
   * that job's own slice rather than the file: a `make test-cov` that
   * appeared in some other job would satisfy a whole-file `toContain` and
   * gate nothing on a PR.
   */
  const testsJob = (() => {
    const start = workflow.indexOf("\n  tests:");
    const end = workflow.indexOf("\n  docker-build:");
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    return workflow.slice(start, end);
  })();

  it("declares nine jobs, which is the check count the merge gate counts", () => {
    // The coordinator's merge gate counts checks from JSON and requires every
    // one of them green. WO-A13 wired five tiers and two coverage floors into
    // the gate and deliberately added no job: the tiers cost seconds and a job
    // costs a runner spin-up plus a full ML install. This is where that
    // decision is written down as a number — a split that anyone makes later
    // is a deliberate edit here plus a message to the coordinator, not a
    // silent change to what a green PR means.
    const jobsBlock = workflow.slice(workflow.indexOf("\njobs:"));
    const jobIds = jobsBlock.match(/^ {2}[a-z][a-z0-9-]*:$/gm) ?? [];
    expect(jobIds.map((line) => line.trim())).toEqual([
      "lint:",
      "typecheck:",
      "tests:",
      "docker-build:",
      "web-image:",
      "web:",
      "web-audit:",
      "web-storybook:",
      "web-e2e:",
    ]);
  });

  it("gates on coverage through the Makefile target, and uploads the report", () => {
    // Through `make test-cov`, not a pytest line copied into the workflow.
    // The project floor is in pyproject.toml and the four per-package floors
    // are Makefile variables; a workflow that restated any of them would be a
    // second copy of a ratchet, and CI would enforce the copy nobody edits.
    expect(testsJob).toContain("make test-cov VENV_PYTHON=python");
    expect(testsJob).toContain("--cov-report=xml:build/coverage.xml");
    expect(testsJob).toContain("name: python-coverage");
    expect(testsJob).toContain("build/coverage.xml");
  });

  it("gates on patch coverage with the floor read out of the Makefile", () => {
    // diff-cover judges the lines the branch changed, which is where a
    // coverage gate earns its keep — project coverage moves logarithmically,
    // so a large untested diff barely twitches it.
    expect(testsJob).toContain("diff_cover.diff_cover_tool");
    expect(testsJob).toContain("--compare-branch=origin/main");
    expect(testsJob).toContain("COV_DIFF");
    // A merge base to compare against; the default shallow fetch has none.
    expect(testsJob).toContain("fetch-depth: 0");
  });

  it("never restates a coverage floor as a literal", () => {
    // The whole file, not just this job: the moment a number appears beside
    // `--fail-under` the Makefile and pyproject stop being the definition,
    // and the ratchet has two values that can disagree.
    expect(workflow).not.toMatch(/--fail-under[= ]\s*['"]?\d/);
  });

  it("runs the e2e tier per PR", () => {
    // 16 tests, 5 s, in a job that already has the interpreter and the
    // dependencies. It was excluded by `-m "not e2e"` and ran nowhere until
    // WO-A13; it is the only tier that drives the router's revision branch,
    // the HITL resume and the SSE frame trajectory end to end.
    expect(testsJob).toContain("make test-e2e VENV_PYTHON=python");
  });

  it("publishes the adversarial suite's attack-success rate as an artifact", () => {
    // Gate A3.7 asks for the ASR with its denominator, and cites a file
    // rather than a number somebody retyped. Two invocations because the CLI
    // either writes its report or gates on it, never both in one pass.
    expect(testsJob).toContain(
      "python -m src.eval.safety_suite --write-baseline build/safety/safety-report.json",
    );
    expect(testsJob).toContain("python -m src.eval.safety_suite | tee build/safety/safety-gate.txt");
    expect(testsJob).toContain("name: safety-attack-success-rate");
    // Under build/, and nowhere near the committed baseline: a baseline a CI
    // run can rewrite is not a baseline. Comments stripped — the step's own
    // prose names the file it must not write to.
    expect(testsJob.replace(/^\s*#.*$/gm, "")).not.toContain(
      "tests/fixtures/safety/baseline.json",
    );
  });

  it("keeps a piped gate from passing on a broken pipe", () => {
    // Two steps pipe a gate's output into `tee`, and this workflow's default
    // shell is `bash -e {0}` — without `pipefail` the exit code is tee's, so
    // a broken coverage floor would report green.
    const blocks = [...testsJob.matchAll(/\n {8}run: \|\n((?: {10}.*\n)+)/g)].map(
      (match) => match[1] ?? "",
    );
    const piped = blocks.filter((body) => body.includes("| tee "));
    // Vacuous truth is the failure mode this test is most likely to reach:
    // a reindented run block matches nothing and the loop below asserts
    // nothing. Both piped gates are named here so that shows up as a failure.
    expect(piped).toHaveLength(2);
    for (const body of piped) {
      expect(body, `a piped run block with no pipefail:\n${body}`).toContain("set -o pipefail");
    }
  });
});

describe("the web tiers are wired", () => {
  it("collects coverage, so the WO-05 thresholds are a gate (C10)", () => {
    expect(workflow).toContain("npm run test -- --coverage");
  });

  it("runs the dependency audit gate (C4) as its own hard-gating job", () => {
    expect(workflow).toContain("npm run audit:gate");

    // 2026-09-04: the gate is a network call to npm's advisory endpoint, and
    // running it inside `web` let a degraded endpoint spend that job's whole
    // 15-minute ceiling — typecheck, Vitest and the build were cancelled
    // unreported on three PRs and three main runs. It is `web-audit` now, and
    // the property that makes that a fix rather than a hiding place is that it
    // stays RED when it cannot run: an audit that did not answer is not a
    // passing audit.
    const start = workflow.indexOf("\n  web-audit:");
    const end = workflow.indexOf("\n  web-storybook:");
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    const auditJob = workflow.slice(start, end);
    expect(auditJob).toContain("name: web dependency audit");
    expect(auditJob).toContain("npm run audit:gate");
    // Comments stripped: the job's own prose says why there is no
    // `continue-on-error` here, and that sentence is not the key.
    expect(auditJob.replace(/^\s*#.*$/gm, "")).not.toMatch(/continue-on-error/);
    // The artifact moved with the step that writes it; it is not duplicated.
    expect(workflow.match(/name: web-npm-audit/g) ?? []).toHaveLength(1);
    expect(auditJob).toContain("name: web-npm-audit");
  });

  it("bounds every npm install, so no step can spend a job's whole ceiling", () => {
    // A job-level `timeout-minutes` is a backstop for the job, not a bound on
    // a step that hangs. npm's default fetch-timeout is five minutes PER
    // REQUEST with two retries, which is how one advisory lookup cost fifteen.
    // The workflow overrides that beside every install, and every install
    // declares its own step timeout.
    const installs = workflow.match(/^ +run: npm ci$/gm) ?? [];
    expect(installs.length).toBeGreaterThanOrEqual(4);
    const bounded = workflow.match(/NPM_CONFIG_FETCH_TIMEOUT/g) ?? [];
    // >= because the audit step carries the same settings for its own fetches.
    expect(bounded.length).toBeGreaterThanOrEqual(installs.length);
  });

  it("runs the route budget check and uploads its report (C7)", () => {
    expect(workflow).toContain("npm run budgets");
    expect(workflow).toContain("web/budget-report.md");
  });

  it("has a Storybook job that both builds and tests the stories (C9)", () => {
    expect(workflow).toContain("web-storybook:");
    expect(workflow).toContain("npm run build-storybook");
    expect(workflow).toContain("npx vitest run --project=storybook");
    expect(workflow).toContain("web/build/storybook");
  });

  it("has an e2e job that seeds the stack and uploads its artifacts (C8)", () => {
    expect(workflow).toContain("web-e2e:");
    expect(workflow).toContain("npm run e2e:stack:up");
    expect(workflow).toContain("npm run e2e:stack:seed");
    // traces, screenshots, video, the HTML report and axe/*.json all live
    // under this one directory (playwright.config.ts / e2e/support/env.ts).
    expect(workflow).toContain("web/build/e2e");
  });

  it("keeps WO-30's boundary evidence, so a green run is readable after the fact", () => {
    // Same argument as the rest of this file: these are edits to a workflow
    // that nothing else can reach. The CSP sweep's TSV and the captured
    // proxy log are the two artifacts a reviewer needs to check criteria 1
    // and 4 against the run that actually happened, and both live under the
    // directory already uploaded whole — so what has to be asserted is that
    // the capture step still exists and still filters to the log's own event
    // name.
    expect(workflow).toContain('"event":"api_proxy_request"');
    expect(workflow).toContain("build/e2e/proxy-log.txt");
    // And the image smoke job proves the two things only the real container
    // can: the nonce-based header, and that scripts/healthcheck.mjs was
    // actually copied into the image.
    expect(workflow).toContain("docker exec web-image-smoke node scripts/healthcheck.mjs");
    expect(workflow).toContain("'strict-dynamic'");
  });

  it("runs chromium only per PR and the full matrix on a schedule", () => {
    // WO-24 criterion 4. `npm run e2e` with no project argument is every
    // project; `--project=chromium` is the per-PR set.
    expect(workflow).toContain("npm run e2e -- --project=chromium");
    expect(workflow).toMatch(/schedule:\s*\n(\s*#[^\n]*\n)*\s*- cron:/);
    expect(workflow).toContain("github.event_name == 'schedule'");
  });
});
