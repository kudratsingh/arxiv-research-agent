import type { ReactNode } from "react";

import { QueryProvider } from "@/app/providers";
import ThreadRailBridge from "@/components/app/ThreadRailBridge";
import { WorkbenchShell } from "@/components/app/WorkbenchShell";

export default function LearnLayout({ children }: { children: ReactNode }) {
  return (
    <WorkbenchShell rail={<ThreadRailBridge />}>
      <QueryProvider>{children}</QueryProvider>
    </WorkbenchShell>
  );
}
