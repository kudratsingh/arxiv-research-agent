import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    coverage: {
      provider: "v8",
      // `text-summary` is the line `npm run test -- --coverage` prints;
      // `json-summary` is the machine-readable copy CI reads to ratchet the
      // thresholds below (05-MIGRATION.md C10, WO-31).
      reporter: ["text", "text-summary", "json-summary"],
      reportsDirectory: "./coverage",
      // Only shipped code counts. The test harness, the config files and the
      // build scripts are not the thing the thresholds are protecting.
      include: ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}", "lib/**/*.{ts,tsx}"],
      exclude: [
        // Generated from `contract/openapi.json`; `npm run contract:check` is
        // what guards it, and a `.d.ts` has no statements to cover anyway.
        "lib/api/generated/**",
      ],
      // SEEDED AT THE MEASURED VALUE, to the decimal, on purpose.
      //
      // 06-WORK-ORDERS.md WO-05 risk note: "a threshold set aspirationally is
      // a threshold that gets skipped". These four numbers are exactly what
      // 456 tests cover as of this commit (re-measured after the rebase onto
      // WO-02's merge) — 533/605 statements, 306/403 branches, 117/135
      // functions, 493/556 lines — so the gate is "do not regress" and
      // nothing else. Raising them is WO-31's ratchet, not a number anyone
      // should edit to make a red run go green.
      thresholds: {
        statements: 88.09,
        branches: 75.93,
        functions: 86.66,
        lines: 88.66,
      },
    },
  },
  resolve: {
    alias: {
      // `import.meta.dirname` rather than `__dirname`: Vite's
      // `configLoader: 'native'` cannot evaluate `__dirname` in an ESM config
      // and warns on every run (05-MIGRATION.md B2). Node 22
      // (`package.json` engines) has had `import.meta.dirname` since 20.11.
      //
      // WO-02: `next/font/local` is a build-time transform, not a runtime
      // module, so every test that reaches app/layout.tsx needs a stand-in.
      // See tests/stubs/next-font-local.ts.
      "next/font/local": path.resolve(import.meta.dirname, "tests/stubs/next-font-local.ts"),
      "@": path.resolve(import.meta.dirname, "."),
    },
  },
});
