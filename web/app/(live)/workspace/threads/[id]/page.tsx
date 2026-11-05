import { Suspense } from "react";
import { notFound } from "next/navigation";
import { LiveLearningThread } from "@/components/workspace/LearningThread";
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params; if (!/^thread-[a-f0-9]{32}$/.test(id)) notFound();
  return <Suspense fallback={<p aria-busy="true">Opening learning thread…</p>}><LiveLearningThread id={id} /></Suspense>;
}
