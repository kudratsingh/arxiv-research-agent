import { LiveReader } from "@/components/workspace/Reader";
import { notFound } from "next/navigation";
import { Suspense } from "react";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let decoded: string;
  try {
    decoded = decodeURIComponent(id);
  } catch {
    notFound();
  }
  return (
    <Suspense fallback={<p className="daily-muted">Opening your source…</p>}>
      <LiveReader id={decoded} />
    </Suspense>
  );
}
