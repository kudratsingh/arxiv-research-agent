"use client";

import { useRouter } from "next/navigation";
import ConversationSidebar from "./ConversationSidebar";

interface ConversationsShellProps {
  activeConversationId: string | null;
  children: React.ReactNode;
}

export default function ConversationsShell({
  activeConversationId,
  children,
}: ConversationsShellProps) {
  const router = useRouter();

  const handleNavigate = (conversationId: string) => {
    router.push(conversationId ? `/c/${conversationId}` : "/");
  };

  return (
    <div className="flex h-screen">
      <ConversationSidebar
        activeConversationId={activeConversationId}
        onNavigate={handleNavigate}
      />
      <div className="flex-1 overflow-hidden">{children}</div>
    </div>
  );
}
