// `web/app/providers.tsx` — the wiring WO-08 mounts.
//
// It is deliberately NOT mounted in `app/layout.tsx` yet: that file is
// WO-08's next write and this work order does not touch it. So the
// evidence here is that the seam works when someone does mount it — the
// provider hands a client down, that client carries WO-11's defaults,
// and an injected client wins so a test or a server prefetch can supply
// its own.

import { createElement } from "react";

import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { Providers, QueryProvider } from "@/app/providers";
import { createQueryClient } from "@/lib/queries/client";

import { renderHook } from "../support/render";

function inProviders(client?: QueryClient) {
  return renderHook(() => useQueryClient(), {
    wrapper: ({ children }) => createElement(Providers, { client, children }),
  });
}

describe("Providers", () => {
  it("supplies a query client to the tree below it", () => {
    const { result } = inProviders();
    expect(result.current).toBeDefined();
    expect(typeof result.current.getQueryCache).toBe("function");
  });

  it("supplies one that carries WO-11's mutation defaults", () => {
    const { result } = inProviders();
    const defaults = result.current.getDefaultOptions();
    expect(defaults.mutations?.retry).toBe(false);
    expect(defaults.mutations?.networkMode).toBe("always");
  });

  it("keeps the same client across re-renders", () => {
    const { result, rerender } = inProviders();
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("prefers an injected client", () => {
    const injected = createQueryClient();
    const { result } = inProviders(injected);
    expect(result.current).toBe(injected);
  });

  it("creates a client per provider, never a module-level singleton", () => {
    // A module-level client would let one request's cache serve another's
    // render on the server.
    const first = inProviders().result.current;
    const second = inProviders().result.current;
    expect(second).not.toBe(first);
  });

  it("exposes the query wiring on its own, for a narrower mount", () => {
    const { result } = renderHook(() => useQueryClient(), {
      wrapper: ({ children }) => createElement(QueryProvider, { children }),
    });
    expect(result.current.getDefaultOptions().mutations?.retry).toBe(false);
  });
});
