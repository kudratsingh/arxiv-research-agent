"use client";

import { useEffect, useRef } from "react";
import { commandForKey, type KeySequence } from "@/lib/workspace/commands";
import { dispatchWorkspaceCommand } from "@/lib/workspace/dispatch";

export function useWorkspaceShortcuts(): void {
  const sequence = useRef<KeySequence | null>(null);
  useEffect(() => {
    function handleKey(event: KeyboardEvent): void {
      const result = commandForKey(event, sequence.current);
      sequence.current = result.sequence;
      if (result.command && dispatchWorkspaceCommand(result.command)) event.preventDefault();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);
}
