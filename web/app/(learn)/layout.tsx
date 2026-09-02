import type { ReactNode } from "react";

import { QueryProvider } from "@/app/providers";
import ThreadRailBridge from "@/components/app/ThreadRailBridge";
import { WorkbenchShell } from "@/components/app/WorkbenchShell";
import { resolveWorkspaceIdentity } from "@/lib/server/identity";

/**
 * WO-W17b made this async for the reason `app/(workspace)/layout.tsx` gives at
 * length: under the pilot edge overlay the identity slot's sentence is a
 * property of the request, and a group layout is the only server component
 * either group mounts `WorkbenchShell` from. Both layouts resolve the same
 * descriptor through the same function, so the two groups cannot drift into
 * saying different things about the same request.
 */
export default async function LearnLayout({
  children,
}: {
  children: ReactNode;
}) {
  const identity = await resolveWorkspaceIdentity();

  return (
    <WorkbenchShell rail={<ThreadRailBridge />} identity={identity}>
      <QueryProvider>{children}</QueryProvider>
    </WorkbenchShell>
  );
}
