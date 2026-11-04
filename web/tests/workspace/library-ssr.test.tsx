import { renderToString } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";
import { LiveLibrary } from "@/components/workspace/Library";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it("renders the Library hydration placeholder without reading browser focus or private records on the server", () => {
  const read = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Browser storage must not be read during server rendering"); });
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  const html = renderToString(<LiveLibrary />);
  expect(html).toContain("Opening your local workspace");
  expect(read).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
  expect(html).not.toContain("Resume this question");
});
