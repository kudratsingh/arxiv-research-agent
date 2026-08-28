// Drift check 2 of 4 (04-ARCHITECTURE.md §3.5) is a byte comparison, and it
// runs as `npm run contract:check` — regenerating `lib/api/generated/schema.d.ts`
// from `contract/openapi.json` and diffing. It is a shell step rather than a
// test because it spawns the generator; CI runs it in the `web` job.
//
// What this file guards is the *conditions that make that check meaningful*,
// which are cheap to assert here and easy to break by accident:
//
//   - the generator must be pinned to an exact version, or a formatting
//     change in a floating minor fails an unchanged main;
//   - the script has to exist and be wired to the checker;
//   - the snapshot has to keep the provenance header check 1 strips.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";

const WEB_ROOT = process.cwd();

function read(relative: string): string {
  return readFileSync(join(WEB_ROOT, relative), "utf8");
}

interface PackageJson {
  scripts: Record<string, string>;
  devDependencies: Record<string, string>;
}

const pkg = JSON.parse(read("package.json")) as PackageJson;

describe("contract/generated types — the drift check's preconditions", () => {
  it("pins openapi-typescript to an exact version", () => {
    const pinned = pkg.devDependencies["openapi-typescript"];
    expect(pinned).toBeDefined();
    // No caret, no tilde, no range. `contract:check` compares bytes, so the
    // generator's own output format is part of the contract.
    expect(pinned).toMatch(/^\d+\.\d+\.\d+$/);
  });

  it("pins zod to an exact version too", () => {
    // Same reasoning one step removed: the fixture parse tests are the other
    // gate on this data, and a validator that changes its behaviour between
    // installs makes them non-reproducible.
    expect(pkg.devDependencies["zod"]).toMatch(/^\d+\.\d+\.\d+$/);
  });

  it("exposes contract:check and points it at the checker", () => {
    expect(pkg.scripts["contract:check"]).toContain(
      "contract/check-generated-types.sh"
    );
    // And the generator script both it and a human would use.
    expect(pkg.scripts["generate:types"]).toContain("./contract/openapi.json");
    expect(pkg.scripts["generate:types"]).toContain(
      "./lib/api/generated/schema.d.ts"
    );
  });

  it("keeps the checker honest about what a failure means", () => {
    const checker = read("contract/check-generated-types.sh");
    expect(checker).toContain("diff -u");
    // A checker that cannot fail is not a check.
    expect(checker).toContain("exit 1");
    // Never `npm install` behind the developer's back.
    expect(checker).toContain("--no-install");
  });

  it("keeps the OpenAPI snapshot's provenance header first, with the strip note", () => {
    const snapshot = JSON.parse(read("contract/openapi.json")) as Record<
      string,
      unknown
    >;
    expect(Object.keys(snapshot)[0]).toBe("x-provenance");
    const provenance = snapshot["x-provenance"] as Record<string, string>;
    expect(provenance.commit).toMatch(/^[0-9a-f]{40}$/);
    // Check 1 (Python) compares against a freshly generated document, which
    // has no such key. The instruction to strip it lives in the file itself
    // because JSON cannot carry a comment.
    const note = provenance.note ?? "";
    expect(note).toContain("x-provenance");
    expect(note.toLowerCase()).toContain("strip");
  });

  it("never hand-edits the generated file", () => {
    const generated = read("lib/api/generated/schema.d.ts");
    expect(generated).toContain("Do not make direct changes to the file");
  });
});
