"use client";

import { FormEvent, KeyboardEvent, useState } from "react";

interface QueryFormProps {
  onSubmit: (query: string) => void | Promise<void>;
  busy: boolean;
  jobId: string | null;
  error: string | null;
}

export default function QueryForm({
  onSubmit,
  busy,
  jobId,
  error,
}: QueryFormProps) {
  const [query, setQuery] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!query.trim() || busy) return;
    await onSubmit(query.trim());
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Cmd/Ctrl + Enter submits — a modest ergonomic touch.
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      void handleSubmit(e as unknown as FormEvent);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-slate-200 bg-slate-50 p-5 dark:border-slate-800 dark:bg-slate-900"
    >
      <label
        htmlFor="query"
        className="mb-2 block text-sm font-semibold"
      >
        Research question
      </label>
      <textarea
        id="query"
        rows={3}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="e.g. What are the latest approaches to reducing hallucination in large language models?"
        className="block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/25 dark:border-slate-700 dark:bg-slate-950 dark:placeholder:text-slate-500"
        autoFocus
      />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={busy || !query.trim()}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? "Running…" : "Run research"}
        </button>
        {jobId && (
          <span className="font-mono text-xs text-slate-500 dark:text-slate-400">
            job {jobId}
          </span>
        )}
      </div>
      <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
        Enter a natural-language question. The workflow searches arXiv,
        reads matching papers, synthesizes a briefing, and self-critiques.
        30-90 seconds per query. Progress streams below.
      </p>
      {error && (
        <p
          role="alert"
          className="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200"
        >
          {error}
        </p>
      )}
    </form>
  );
}
