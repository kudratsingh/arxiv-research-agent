"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage, workspaceRequest, type WorkspaceState } from "./api";
import { publishResolvedMode } from "./productContext";
import { useWorkspaceSearch } from "./urlState";

function stateEndpoint(params: URLSearchParams) {
  const query = new URLSearchParams(), mode = params.get("mode");
  if (mode !== null) query.set("mode", mode === "research" ? "research" : "learn");
  for (const field of ["project", "thread"]) { const value = params.get(field); if (value !== null) query.set(field, value); }
  return `context/state${query.size ? `?${query}` : ""}`;
}
export function useWorkspace({ retainDuringContextChange = false }: { retainDuringContextChange?: boolean } = {}) {
  const endpoint = stateEndpoint(new URLSearchParams(useWorkspaceSearch()));
  const [snapshot, commitSnapshot] = useState<{ endpoint: string; state: WorkspaceState } | null>(null);
  const state = snapshot && (snapshot.endpoint === endpoint || retainDuringContextChange) ? snapshot.state : null;
  const contextPending = snapshot !== null && snapshot.endpoint !== endpoint;
  const sequence = useRef(0), lifecycle = useRef({ active: true });
  const current = useCallback(() => stateEndpoint(new URLSearchParams(location.search)) === endpoint, [endpoint]);
  const setState = useCallback((next: WorkspaceState) => { if (current()) commitSnapshot({ endpoint, state: next }); }, [endpoint, current]);
  const [error, setError] = useState("");
  const [settled, setSettled] = useState<string | null>(null), [reloading, setReloading] = useState(false);
  const read = useCallback(async (signal?: AbortSignal) => {
    const request = ++sequence.current;
    const cycle = lifecycle.current;
    const valid = () => cycle.active && !signal?.aborted && request === sequence.current && current();
    try {
      const key = `${location.pathname}${location.search}`;
      const next = await workspaceRequest<WorkspaceState>(endpoint, undefined, signal);
      if (!valid()) return;
      if (next.context) publishResolvedMode(next.context.mode, key);
      commitSnapshot({ endpoint, state: next });
      setError("");
    } catch (failure) {
      if (valid()) setError(errorMessage(failure));
    } finally {
      if (valid()) { setSettled(endpoint); setReloading(false); }
    }
  }, [endpoint, current]);
  const reload = useCallback(() => { if (!current()) return Promise.resolve(); setReloading(true); return read(); }, [read, current]);
  useEffect(() => {
    const controller = new AbortController();
    const cycle = { active: true }; lifecycle.current = cycle;
    queueMicrotask(() => { if (!controller.signal.aborted) void read(controller.signal); });
    return () => { cycle.active = false; controller.abort(); };
  }, [read]);
  return { state, setState, error, loading: settled !== endpoint || reloading, reload, contextPending };
}
