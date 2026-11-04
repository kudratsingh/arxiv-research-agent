"use client";

import { createContext, useContext, type ReactNode } from "react";

const SyntheticPreviewContext = createContext(false);

/** Only the server's explicit configuration marks data as a design preview. */
export function SyntheticPreviewProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  return <SyntheticPreviewContext.Provider value={enabled}>{children}</SyntheticPreviewContext.Provider>;
}

export function useSyntheticPreview(): boolean {
  return useContext(SyntheticPreviewContext);
}
