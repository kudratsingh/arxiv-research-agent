"use client";

import { useParams } from "next/navigation";
import ConversationThread from "@/components/ConversationThread";
import ConversationsShell from "@/components/ConversationsShell";

export default function ConversationPage() {
  const params = useParams<{ id: string }>();
  const conversationId = params?.id ?? "";
  return (
    <ConversationsShell activeConversationId={conversationId}>
      <ConversationThread conversationId={conversationId} />
    </ConversationsShell>
  );
}
