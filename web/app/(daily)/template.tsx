"use client";

import { DailyShell } from "@/components/daily/DailyShell";

/** Keep this shell's client boundary on its own route segment (ADR 0103). */
export default function DailyTemplate({ children }: { children: React.ReactNode }) {
  return <DailyShell>{children}</DailyShell>;
}
