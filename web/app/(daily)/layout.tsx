import { notFound } from "next/navigation";

export default function DailyLayout({ children }: { children: React.ReactNode }) {
  if (process.env.WORKSPACE_PREVIEW !== "1") notFound();
  return children;
}
