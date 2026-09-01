import { PathDetailSurface } from "@/components/features/PathDetailSurface";

export default async function LearnPathPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <PathDetailSurface pathId={id} />;
}
