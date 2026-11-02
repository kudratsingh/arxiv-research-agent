"use client";

import { DailyShell } from "@/components/daily/DailyShell";

/** Keep this shell's client boundary on its own route segment (the workspace ADR proposal). */
export default function DailyTemplate({ children }: { children: React.ReactNode }) {
  return <DailyShell>{children}</DailyShell>;
}
