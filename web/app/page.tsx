import ResearchApp from "@/components/ResearchApp";
import { API_BASE } from "@/lib/api";

export default function HomePage() {
  return (
    <main className="mx-auto max-w-4xl px-5 pb-24 pt-10">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">
          arxiv-research-agent
        </h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Multi-agent research assistant for ML/AI papers.{" "}
          <a
            href="https://github.com/kudratsingh/arxiv-research-agent"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline dark:text-blue-400"
          >
            Source &rarr;
          </a>
        </p>
      </header>

      <ResearchApp />

      <footer className="mt-12 border-t border-slate-200 pt-4 text-center text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
        API surface at{" "}
        <a
          href={`${API_BASE}/docs`}
          className="text-blue-600 hover:underline dark:text-blue-400"
        >
          {API_BASE}/docs
        </a>
      </footer>
    </main>
  );
}
