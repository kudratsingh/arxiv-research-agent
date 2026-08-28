import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

import { uninstallFakeEventSource } from "./tests/support/FakeEventSource";
import { clearTestTheme } from "./tests/support/render";

// Testing Library doesn't auto-cleanup with Vitest's globals; do it
// explicitly so tests are isolated from one another.
//
// The other two are global state a single test file can otherwise leak into
// the next one: `globalThis.EventSource` (jsdom supplies none, so a stub left
// installed is indistinguishable from a browser that has one) and the theme
// attributes `tests/support/render.tsx` writes onto `<html>`.
afterEach(() => {
  cleanup();
  uninstallFakeEventSource();
  clearTestTheme();
});
