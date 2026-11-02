"use client";

import { useCallback, useEffect, useState } from "react";
import { errorMessage, workspaceRequest, type WorkspaceState } from "./api";

export function useWorkspace() {
  const [state, setState] = useState<WorkspaceState | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const next = await workspaceRequest<WorkspaceState>("state");
      setState(next);
      setError("");
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    workspaceRequest<WorkspaceState>("state", undefined, controller.signal)
      .then((next) => {
        setState(next);
        setError("");
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);
  return { state, setState, error, loading, reload };
}
