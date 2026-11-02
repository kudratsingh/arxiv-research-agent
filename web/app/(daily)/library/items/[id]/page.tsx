import { notFound } from "next/navigation";
import { Reader } from "@/components/daily/Reader";
import { ITEMS } from "@/lib/daily/fixtures";
export default async function ItemPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const item = ITEMS.find(item => item.id === id);
  if (!item) notFound();
  return <Reader item={item} />;
}
