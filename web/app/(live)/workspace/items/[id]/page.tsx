import { LiveReader } from "@/components/workspace/Reader";
import { notFound } from "next/navigation";
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
  return <LiveReader id={decoded} />;
}
