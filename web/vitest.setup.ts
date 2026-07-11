import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Testing Library doesn't auto-cleanup with Vitest's globals; do it
// explicitly so tests are isolated from one another.
afterEach(() => {
  cleanup();
});
