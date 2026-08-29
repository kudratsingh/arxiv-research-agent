/**
 * WO-24 — the dependency audit gate (05-MIGRATION.md C4).
 *
 * The script shells out to `npm audit`, so what is tested here is everything
 * *except* that call: the report reader, the exceptions contract, and the
 * three-way evaluation. Reports are synthetic fixtures in npm's own shape,
 * which is what lets a test assert "a NEW advisory on an already-excepted
 * package fails" without waiting for one to be published.
 *
 * The checked-in `web/audit-exceptions.json` is also asserted against, so an
 * entry that loses its justification, its date or its advisory ids fails the
 * unit suite and not only the CI job.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  BLOCKING_SEVERITIES,
  MIN_JUSTIFICATION,
  REQUIRED_FIELDS,
  advisoryIdsOf,
  blockingFindings,
  evaluateFullTree,
  evaluateProduction,
  loadExceptions,
  parseExceptions,
  renderSummary,
  type AuditReport,
  type Exception,
} from "../scripts/audit-gate.mjs";

const WEB_ROOT = path.resolve(__dirname, "..");
const SCRIPT_PATH = path.join(WEB_ROOT, "scripts", "audit-gate.mjs");

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/**
 * The real shape, reduced: `image-size` carries the advisories,
 * `vite-plugin-storybook-nextjs` depends on it, `@storybook/nextjs-vite`
 * depends on that. npm reports all three at high severity, which is why the
 * "3 advisories" the tree reports are three packages and two GHSAs.
 */
function storybookChain(): AuditReport {
  return {
    vulnerabilities: {
      "image-size": {
        severity: "high",
        isDirect: false,
        nodes: ["node_modules/image-size"],
        via: [
          { source: 1138808, name: "image-size", title: "ICNS parser DoS", severity: "high" },
          { source: 1138809, name: "image-size", title: "JXL/HEIF parser DoS", severity: "high" },
        ],
        effects: ["vite-plugin-storybook-nextjs"],
      },
      "vite-plugin-storybook-nextjs": {
        severity: "high",
        isDirect: false,
        nodes: ["node_modules/vite-plugin-storybook-nextjs"],
        via: ["image-size"],
        effects: ["@storybook/nextjs-vite"],
      },
      "@storybook/nextjs-vite": {
        severity: "high",
        isDirect: true,
        nodes: ["node_modules/@storybook/nextjs-vite"],
        via: ["vite-plugin-storybook-nextjs"],
        effects: [],
      },
    },
  };
}

function exception(overrides: Partial<Exception> = {}): Record<string, unknown> {
  return {
    package: "image-size",
    advisories: [1138808, 1138809],
    path: "@storybook/nextjs-vite > vite-plugin-storybook-nextjs > image-size",
    date: "2026-08-29",
    owner: "WO-24",
    severity: "high",
    justification:
      "Dev-only Storybook build dependency with no fix available; not reachable from the production tree.",
    ...overrides,
  };
}

/** The three entries the storybook chain needs, as the real file supplies them. */
function chainExceptions(): Exception[] {
  return parseExceptions({
    exceptions: [
      exception(),
      exception({
        package: "vite-plugin-storybook-nextjs",
        path: "@storybook/nextjs-vite > vite-plugin-storybook-nextjs",
      } as Partial<Exception>),
      exception({
        package: "@storybook/nextjs-vite",
        path: "@storybook/nextjs-vite",
      } as Partial<Exception>),
    ],
  });
}

// ---------------------------------------------------------------------------
// Reading a report
// ---------------------------------------------------------------------------

describe("reading an npm audit report", () => {
  it("resolves a dependent package to the advisories underneath it", () => {
    const report = storybookChain();
    expect([...advisoryIdsOf(report, "image-size")]).toEqual([1138808, 1138809]);
    // Two hops from the package that actually carries the defect.
    expect([...advisoryIdsOf(report, "@storybook/nextjs-vite")].sort()).toEqual([
      1138808, 1138809,
    ]);
  });

  it("does not loop on a cyclic via chain", () => {
    const report: AuditReport = {
      vulnerabilities: {
        a: { severity: "high", via: ["b"] },
        b: { severity: "high", via: ["a"] },
      },
    };
    expect([...advisoryIdsOf(report, "a")]).toEqual([]);
  });

  it("keeps only high and critical findings", () => {
    const report = storybookChain();
    report.vulnerabilities!["some-moderate-thing"] = {
      severity: "moderate",
      via: [{ source: 42, title: "not blocking" }],
    };
    expect(BLOCKING_SEVERITIES).toEqual(["high", "critical"]);
    expect(blockingFindings(report).map((f) => f.package)).toEqual([
      "@storybook/nextjs-vite",
      "image-size",
      "vite-plugin-storybook-nextjs",
    ]);
  });
});

// ---------------------------------------------------------------------------
// The exceptions contract
// ---------------------------------------------------------------------------

describe("the exceptions file contract", () => {
  it("accepts a complete entry", () => {
    const [entry] = parseExceptions({ exceptions: [exception()] });
    expect(entry?.package).toBe("image-size");
    expect(entry?.advisories).toEqual([1138808, 1138809]);
  });

  it("accepts an empty list — the file's correct state once the chain is fixed", () => {
    expect(parseExceptions({ exceptions: [] })).toEqual([]);
  });

  it.each(REQUIRED_FIELDS)("rejects an entry with no %s", (field) => {
    const entry = exception();
    delete entry[field];
    expect(() => parseExceptions({ exceptions: [entry] })).toThrow(field);
  });

  it("rejects an empty justification", () => {
    expect(() => parseExceptions({ exceptions: [exception({ justification: "" })] })).toThrow(
      /no written justification/,
    );
  });

  it("rejects a perfunctory justification", () => {
    // Same floor and the same reason as WO-22's axe allowlist: "wontfix" is
    // not a justification, it is a shrug.
    expect("wontfix".length).toBeLessThan(MIN_JUSTIFICATION);
    expect(() =>
      parseExceptions({ exceptions: [exception({ justification: "wontfix" })] }),
    ).toThrow(/no written justification/);
  });

  it("rejects a path that does not end at the package it covers", () => {
    expect(() =>
      parseExceptions({ exceptions: [exception({ path: "@storybook/nextjs-vite" })] }),
    ).toThrow(/must end at the package it covers/);
  });

  it("rejects a date that is not YYYY-MM-DD", () => {
    expect(() => parseExceptions({ exceptions: [exception({ date: "yesterday" })] })).toThrow(
      /YYYY-MM-DD/,
    );
  });

  it("rejects an empty or non-integer advisory list", () => {
    expect(() => parseExceptions({ exceptions: [exception({ advisories: [] })] })).toThrow(
      /advisories/,
    );
    expect(() =>
      parseExceptions({
        exceptions: [exception({ advisories: ["GHSA-w3rx-r6r6-pgpr"] } as never)],
      }),
    ).toThrow(/advisories/);
  });

  it("rejects the same package twice", () => {
    expect(() => parseExceptions({ exceptions: [exception(), exception()] })).toThrow(
      /listed twice/,
    );
  });

  it("rejects a bare array — the file carries its policy alongside the list", () => {
    expect(() => parseExceptions([exception()])).toThrow(/"exceptions" array/);
  });
});

// ---------------------------------------------------------------------------
// Evaluation
// ---------------------------------------------------------------------------

describe("the production half of the gate", () => {
  it("passes on an empty tree", () => {
    expect(evaluateProduction({ report: { vulnerabilities: {} } }).ok).toBe(true);
  });

  it("fails on any high advisory, with no exception mechanism at all", () => {
    // The exceptions file is not even an argument to this function. That is
    // the ruling: a production advisory is fixed, upgraded or removed.
    const result = evaluateProduction({ report: storybookChain() });
    expect(result.ok).toBe(false);
    expect(result.findings).toHaveLength(3);
  });
});

describe("the dev half of the gate", () => {
  it("passes when every finding is accounted for", () => {
    const result = evaluateFullTree({
      report: storybookChain(),
      exceptions: chainExceptions(),
    });
    expect(result.ok).toBe(true);
    expect(result.accepted).toHaveLength(3);
    expect(result.unlisted).toHaveLength(0);
    expect(result.stale).toHaveLength(0);
  });

  it("fails on a finding no entry covers", () => {
    const report = storybookChain();
    report.vulnerabilities!["some-new-package"] = {
      severity: "critical",
      via: [{ source: 9999, title: "arbitrary code execution" }],
      nodes: ["node_modules/some-new-package"],
    };
    const result = evaluateFullTree({ report, exceptions: chainExceptions() });
    expect(result.ok).toBe(false);
    expect(result.unlisted.map((u) => u.finding.package)).toEqual(["some-new-package"]);
  });

  it("fails on a NEW advisory against an already-excepted package", () => {
    // The failure mode an allowlist keyed on package name alone would miss:
    // the entry says "these two advisories are accepted", not "this package
    // is exempt".
    const report = storybookChain();
    report.vulnerabilities!["image-size"]!.via!.push({
      source: 1200000,
      title: "something new and worse",
      severity: "critical",
    });
    const result = evaluateFullTree({ report, exceptions: chainExceptions() });
    expect(result.ok).toBe(false);
    expect(result.unlisted.map((u) => u.finding.package)).toContain("image-size");
    expect(result.unlisted[0]?.entry).not.toBeNull();
  });

  it("fails on a stale entry, so an exception cannot outlive its advisory", () => {
    const result = evaluateFullTree({
      report: { vulnerabilities: {} },
      exceptions: chainExceptions(),
    });
    expect(result.ok).toBe(false);
    expect(result.stale.map((entry) => entry.package)).toEqual([
      "image-size",
      "vite-plugin-storybook-nextjs",
      "@storybook/nextjs-vite",
    ]);
  });

  it("names the mismatch in the summary rather than printing a count", () => {
    const report = storybookChain();
    delete report.vulnerabilities!["image-size"];
    const full = evaluateFullTree({ report, exceptions: chainExceptions() });
    const summary = renderSummary({
      production: evaluateProduction({ report: { vulnerabilities: {} } }),
      full,
      exceptions: chainExceptions(),
    });
    expect(summary).toContain("stale exception");
    expect(summary).toContain("image-size");
  });
});

// ---------------------------------------------------------------------------
// The checked-in file, and the script's own properties
// ---------------------------------------------------------------------------

describe("web/audit-exceptions.json as checked in", () => {
  const exceptions = loadExceptions(WEB_ROOT);

  it("covers the Storybook image-size chain and nothing else", () => {
    // Three entries, two upstream GHSAs. If this list grows, the growth is a
    // review conversation — which is the point of it being a file.
    expect(exceptions.map((entry) => entry.package).sort()).toEqual([
      "@storybook/nextjs-vite",
      "image-size",
      "vite-plugin-storybook-nextjs",
    ]);
    for (const entry of exceptions) {
      expect(entry.advisories).toEqual([1138808, 1138809]);
    }
  });

  it("gives every entry a real justification and an owner", () => {
    for (const entry of exceptions) {
      expect(entry.justification.length, entry.package).toBeGreaterThan(MIN_JUSTIFICATION);
      expect(entry.owner, entry.package).toBeTruthy();
    }
  });

  it("says in the file itself that an exception may never cover a production package", () => {
    const raw = JSON.parse(
      readFileSync(path.join(WEB_ROOT, "audit-exceptions.json"), "utf8"),
    ) as { policy?: string };
    expect(raw.policy).toMatch(/production/i);
  });
});

describe("the gate has no escape hatch", () => {
  const source = readFileSync(SCRIPT_PATH, "utf8");

  it("reads no environment variable", () => {
    // Same property `route-budgets.mjs` holds, and for the same reason: an
    // env var that turns a gate off is a gate that is off.
    expect(source).not.toMatch(/process\.env/);
  });

  it("has no skip/ignore/force flag", () => {
    expect(source).not.toMatch(/--(skip|ignore|force|no-fail|allow-fail)/);
    expect(source).not.toMatch(/SKIP_AUDIT|AUDIT_SKIP|IGNORE_AUDIT/i);
  });

  it("refuses any command-line argument", () => {
    expect(source).toContain("this check takes no arguments");
  });

  it("never lowers the audit level below high", () => {
    expect(source).toContain("--audit-level=high");
    expect(source).not.toMatch(/--audit-level=(critical|moderate|low|none)/);
  });

  it("is wired to an npm script", () => {
    const pkg = JSON.parse(readFileSync(path.join(WEB_ROOT, "package.json"), "utf8")) as {
      scripts: Record<string, string>;
    };
    expect(pkg.scripts["audit:gate"]).toBe("node scripts/audit-gate.mjs");
  });
});
