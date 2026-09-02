import { SessionDetailSurface } from "@/components/features/SessionDetailSurface";

export default async function LearnSessionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <SessionDetailSurface sessionId={id} />;
}
