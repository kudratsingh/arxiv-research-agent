import { notFound } from "next/navigation";

export default function LiveLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  if (process.env.WORKSPACE_LIVE !== "1") notFound();
  return children;
}
