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
  },
  resolve: {
    alias: {
      // WO-02: `next/font/local` is a build-time transform, not a runtime
      // module, so every test that reaches app/layout.tsx needs a stand-in.
      // See tests/stubs/next-font-local.ts.
      "next/font/local": path.resolve(__dirname, "tests/stubs/next-font-local.ts"),
      "@": path.resolve(__dirname, "."),
    },
  },
});
