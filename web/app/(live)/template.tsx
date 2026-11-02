"use client";

import { WorkspaceShell } from "@/components/workspace/Shell";

export default function LiveTemplate({
  children,
}: {
  children: React.ReactNode;
}) {
  return <WorkspaceShell>{children}</WorkspaceShell>;
}
