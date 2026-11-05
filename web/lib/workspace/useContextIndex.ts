import { useCallback, useEffect, useRef, useState } from "react";
import { contextRequest, errorMessage, type ContextIndex } from "./api";
import { publishResolvedMode } from "./productContext";
export function invalidateContextIndex() { window.dispatchEvent(new Event("workspace:context-index")); }

export function useContextIndex() {
  const [index, setIndex] = useState<ContextIndex | null>(null);
  const [error, setError] = useState("");
  const sequence = useRef(0), mounted = useRef(true);
  const reload = useCallback(async () => {
    const request = ++sequence.current;
    const key = `${location.pathname}${location.search}`;
    try { const next = await contextRequest<ContextIndex>(); if (mounted.current && request === sequence.current) { publishResolvedMode(next.preferences.data.default_mode, key); setIndex(next); setError(""); } return next; }
    catch (failure) { if (mounted.current && request === sequence.current) setError(errorMessage(failure)); return null; }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    mounted.current = true; const request = ++sequence.current;
    const key = `${location.pathname}${location.search}`;
    contextRequest<ContextIndex>("", undefined, controller.signal).then(value => {
      if (!controller.signal.aborted && request === sequence.current) { publishResolvedMode(value.preferences.data.default_mode, key); setIndex(value); setError(""); }
    }).catch(failure => { if (!controller.signal.aborted && request === sequence.current) setError(errorMessage(failure)); });
    const changed = () => { void reload(); }; window.addEventListener("workspace:context-index", changed);
    return () => { controller.abort(); mounted.current = false; window.removeEventListener("workspace:context-index", changed); };
  }, [reload]);
  return { index, error, reload, setIndex };
}
