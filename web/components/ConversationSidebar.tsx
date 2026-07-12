"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  createConversation,
  deleteConversation,
  listConversations,
} from "@/lib/api";
import type { ConversationListItem } from "@/lib/types";

interface ConversationSidebarProps {
  activeConversationId: string | null;
  onNavigate: (conversationId: string) => void;
}

export default function ConversationSidebar({
  activeConversationId,
  onNavigate,
}: ConversationSidebarProps) {
  const [items, setItems] = useState<ConversationListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await listConversations();
      setItems(list);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleNew = useCallback(async () => {
    setCreating(true);
    try {
      const conv = await createConversation();
      await load();
      onNavigate(conv.conversation_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  }, [load, onNavigate]);

  const handleDelete = useCallback(
    async (id: string) => {
      if (!confirm("Delete this conversation and all its jobs?")) return;
      try {
        await deleteConversation(id);
        await load();
        if (activeConversationId === id) {
          onNavigate("");
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [activeConversationId, load, onNavigate]
  );

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900">
      <div className="px-4 pt-5">
        <button
          type="button"
          onClick={handleNew}
          disabled={creating}
          className="w-full rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {creating ? "Creating…" : "+ New conversation"}
        </button>
      </div>
      <div className="px-4 py-3 text-[0.65rem] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
        Recent
      </div>
      <ul className="flex-1 overflow-y-auto px-2 pb-4">
        {items === null && !error && (
          <li className="px-2 py-1 text-xs text-slate-500 dark:text-slate-400">
            Loading…
          </li>
        )}
        {items !== null && items.length === 0 && (
          <li className="px-2 py-1 text-xs text-slate-500 dark:text-slate-400">
            No conversations yet.
          </li>
        )}
        {items?.map((c) => (
          <li key={c.conversation_id}>
            <div className="group flex items-stretch">
              <Link
                href={`/c/${c.conversation_id}`}
                onClick={() => onNavigate(c.conversation_id)}
                className={`flex-1 truncate rounded-l-md px-3 py-2 text-sm ${
                  c.conversation_id === activeConversationId
                    ? "bg-blue-100 font-medium text-blue-900 dark:bg-blue-950/60 dark:text-blue-100"
                    : "text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800"
                }`}
                title={c.title}
              >
                {c.title}
              </Link>
              <button
                type="button"
                onClick={() => void handleDelete(c.conversation_id)}
                aria-label={`Delete ${c.title}`}
                className="rounded-r-md px-2 text-xs text-slate-400 opacity-0 hover:bg-red-100 hover:text-red-700 group-hover:opacity-100 dark:hover:bg-red-950/40 dark:hover:text-red-200"
              >
                &times;
              </button>
            </div>
          </li>
        ))}
      </ul>
      {error && (
        <div
          role="alert"
          className="mx-2 mb-2 rounded-md border border-red-300 bg-red-50 px-2 py-1 text-xs text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200"
        >
          {error}
        </div>
      )}
    </aside>
  );
}
