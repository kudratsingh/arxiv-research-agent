import { notFound } from "next/navigation";
import { SyntheticPreviewProvider } from "@/components/workspace/PreviewContext";

// Read server runtime configuration for each request, including after startup.
export const dynamic = "force-dynamic";

export default function LiveLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  if (process.env.WORKSPACE_LIVE !== "1") notFound();
  return <SyntheticPreviewProvider enabled={process.env.WORKSPACE_SYNTHETIC_PREVIEW === "1"}>{children}</SyntheticPreviewProvider>;
}
