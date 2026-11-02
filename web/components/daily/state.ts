"use client";
import { useSyncExternalStore } from "react";
import { previewStore } from "@/lib/daily/store";

export function usePreview() {
  const snapshot = useSyncExternalStore(
    previewStore.subscribe,
    previewStore.getSnapshot,
    previewStore.getServerSnapshot,
  );
  return { ...snapshot, update: previewStore.update };
}
