"use client";
import Link from "next/link";
import { ITEMS } from "@/lib/daily/fixtures";
import { usePreview } from "./state";

export function Library() {
  const { data } = usePreview();
  const items = ITEMS.filter((item) => data.saved.includes(item.id));
  function exportNotes() {
    const body = [
      "# My research workspace — preview export",
      "Fictional source material; user notes below are user-authored.",
      ...data.entries.flatMap((entry) => [
        `## ${entry.kind}: ${entry.body}`,
        `Source: ${ITEMS.find((item) => item.id === entry.itemId)?.title ?? entry.itemId} · preview source version`,
        "",
      ]),
    ].join("\n\n");
    const url = URL.createObjectURL(
      new Blob([body], { type: "text/markdown" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "research-preview-notes.md";
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <>
      <div className="daily-page-meta">
        <span className="daily-eyebrow">Your research memory</span>
        <Link className="daily-link" href="/today" prefetch={false}>
          ← Today
        </Link>
      </div>
      <div className="daily-intro">
        <div>
          <h1>Keep the useful parts.</h1>
          <p>Saved sources, your questions, and a place to pick up again.</p>
        </div>
        <button
          className="daily-secondary"
          onClick={exportNotes}
          disabled={!data.entries.length}
        >
          Export notes as Markdown
        </button>
      </div>
      <div className="daily-columns">
        <section>
          <h2>Saved reading</h2>
          {items.length ? (
            items.map((item) => (
              <article key={item.id} className="daily-item">
                <div className="daily-item-meta">
                  <span>{item.kind}</span>
                  <span>
                    {item.scope} · {item.version}
                  </span>
                </div>
                <h3>
                  <Link
                    href={`/library/items/${item.id}#${data.anchors[item.id] ?? "source"}`}
                    prefetch={false}
                  >
                    {item.title}
                  </Link>
                </h3>
                <p>{item.caveat}</p>
                <Link
                  className="daily-link"
                  href={`/library/items/${item.id}#${data.anchors[item.id] ?? "source"}`}
                  prefetch={false}
                >
                  Resume reading →
                </Link>
              </article>
            ))
          ) : (
            <div className="daily-empty">
              <p>
                No saved items yet. Open a source and save what deserves another
                look.
              </p>
              <Link href="/today" prefetch={false} className="daily-link">
                Find something to read →
              </Link>
            </div>
          )}
        </section>
        <section id="questions" className="daily-context">
          <span className="daily-eyebrow">Question notebook</span>
          <h2>
            Your thread,
            <br />
            across visits.
          </h2>
          {data.entries.length ? (
            data.entries.map((entry) => (
              <article className="daily-notebook-entry" key={entry.id}>
                <span className="daily-eyebrow">
                  Your {entry.kind.replace("-", " ")}
                </span>
                <p>{entry.body}</p>
                <Link
                  href={`/library/items/${entry.itemId}#notes`}
                  prefetch={false}
                  className="daily-link"
                >
                  Reopen with source →
                </Link>
              </article>
            ))
          ) : (
            <p>
              Pin a question in the reader. It will stay linked to the source
              version, separate from any generated answer.
            </p>
          )}
          <p className="daily-muted">
            Preview data is stored in this browser. It is not synced or backed
            up. Export your notes before clearing browser data.
          </p>
        </section>
      </div>
    </>
  );
}
