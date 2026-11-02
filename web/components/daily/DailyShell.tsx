import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/patterns/ThemeToggle";
import { SkipLink } from "@/components/primitives/SkipLink";
import { usePreview } from "./state";
import "./daily.css";

export function DailyShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { storage } = usePreview();
  return (
    <div className="daily-app font-ui">
      <SkipLink />
      <header className="daily-header">
        <Link href="/today" prefetch={false} className="daily-brand">
          <span className="daily-brand-mark" aria-hidden="true">
            r<span>·</span>
          </span>
          <span>
            Research workspace
            <span className="daily-brand-sub">
              A place to follow a question.
            </span>
          </span>
        </Link>
        <div className="daily-header-actions">
          <ThemeToggle />
          <Link className="daily-link" href="/" prefetch={false}>
            Research a question <span aria-hidden="true">↗</span>
          </Link>
        </div>
      </header>
      <div className="daily-preview-bar">
        <span className="daily-dot" aria-hidden="true" />
        <strong>Design preview</strong>
        <span>Fictional sources · generation off · no live intake</span>
      </div>
      <div className="daily-frame">
        <aside className="daily-sidebar">
          <nav aria-label="Research workspace">
            {[
              ["/today", "Today", "◷"],
              ["/library", "Library", "▤"],
              ["/interests", "Interests", "⌕"],
            ].map(([href, label, icon]) => (
              <Link
                key={href}
                href={href!}
                prefetch={false}
                aria-current={path.startsWith(href!) ? "page" : undefined}
              >
                <span aria-hidden="true">{icon}</span>
                {label}
              </Link>
            ))}
          </nav>
          <div className="daily-sidebar-note">
            <span className="daily-eyebrow">Your workspace</span>
            <p>
              Discover. Understand.
              <br />
              Keep the thread.
            </p>
            <Link href="/learn" prefetch={false}>
              Guided reading <span aria-hidden="true">↗</span>
            </Link>
          </div>
          <p className="daily-storage">
            {storage === "unavailable"
              ? "Browser storage unavailable. Changes last only in this open tab; export your notes."
              : "Preview notes stay in this browser. Export them from Library."}
          </p>
        </aside>
        <main id="main" tabIndex={-1} className="daily-main">
          {children}
        </main>
      </div>
    </div>
  );
}
