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

describe("the web tiers are wired", () => {
  it("collects coverage, so the WO-05 thresholds are a gate (C10)", () => {
    expect(workflow).toContain("npm run test -- --coverage");
  });

  it("runs the dependency audit gate (C4)", () => {
    expect(workflow).toContain("npm run audit:gate");
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

  it("runs chromium only per PR and the full matrix on a schedule", () => {
    // WO-24 criterion 4. `npm run e2e` with no project argument is every
    // project; `--project=chromium` is the per-PR set.
    expect(workflow).toContain("npm run e2e -- --project=chromium");
    expect(workflow).toMatch(/schedule:\s*\n(\s*#[^\n]*\n)*\s*- cron:/);
    expect(workflow).toContain("github.event_name == 'schedule'");
  });
});
