"use client";
import Link from "next/link";
import { Announcement } from "./Announcement";
import { ITEMS, SOURCE_CHECKS } from "@/lib/daily/fixtures";
import { STREAMS } from "@/lib/daily/profile";
import { usePreview } from "./state";

export function Today() {
  const { data, update } = usePreview();
  const active = data.topics.length + data.customTopics.length > 0;
  const matches = ITEMS.filter(
    (item) =>
      item.topics.some((topic) =>
        data.topics.some(
          (selected) => selected === topic || selected.startsWith(`${topic}/`),
        ),
      ) ||
      (item.id === "measurement" &&
        data.topics.some((topic) => topic.startsWith("ml:"))),
  );
  const visible = data.minutes === 5 ? matches.slice(0, 1) : matches;
  const last = data.entries.at(-1);
  return (
    <>
      <div className="daily-page-meta">
        <span className="daily-eyebrow">
          Monday · 02 November 2026 · sample edition
        </span>
        <Link href="/interests" prefetch={false} className="daily-link">
          {data.configured
            ? "Edit your interests"
            : "Tune the suggested ML lens"}{" "}
          <span aria-hidden="true">↗</span>
        </Link>
      </div>
      <div className="daily-intro">
        <div>
          <h1>
            What changed.
            <br />
            <em>What to investigate.</em>
          </h1>
          <p>A finite briefing, with room to follow a question.</p>
        </div>
        <fieldset className="daily-time">
          <legend>Time for reading</legend>
          {[5, 15, 45].map((minutes) => (
            <button
              key={minutes}
              aria-pressed={data.minutes === minutes}
              onClick={() => update((d) => ({ ...d, minutes }))}
            >
              {minutes} min
            </button>
          ))}
        </fieldset>
      </div>
      <div className="daily-columns">
        <div>
          <details className="daily-coverage">
            <summary>
              <span className="daily-status-dot" aria-hidden="true" />
              Sample coverage: 5 of 6 checks available{" "}
              <span>One source delayed</span>
            </summary>
            <p>
              These checks are fictional. No feeds are connected. An incomplete
              check is not “no new papers.”
            </p>
            <ul>
              {SOURCE_CHECKS.map((source) => (
                <li key={source.name}>
                  <strong>{source.name}</strong>
                  <span className={!source.ok ? "daily-warning" : ""}>
                    {source.status}
                  </span>
                </li>
              ))}
            </ul>
          </details>
          {!active ? (
            <section className="daily-empty">
              <h2>Start with a question or an interest.</h2>
              <p>
                Choose a topic to shape this sample briefing. All fields are
                available to explore; live coverage is separate.
              </p>
              <Link className="daily-button" href="/interests" prefetch={false}>
                Choose interests
              </Link>
            </section>
          ) : (
            <section aria-labelledby="changes-title">
              <div className="daily-section-heading">
                <h2 id="changes-title">
                  {data.done ? "Kept for another look" : "Changes to consider"}
                </h2>
                <span>
                  {visible.length} {visible.length === 1 ? "item" : "items"} ·{" "}
                  {data.configured ? "your selected lens" : "suggested ML lens"}
                </span>
              </div>
              {visible.length === 0 ? (
                <p>
                  No sample items match yet. Your custom interests are saved;
                  real source coverage comes next.
                </p>
              ) : (
                visible.map((item, index) => (
                  <article
                    className={`daily-item ${index === 0 ? "daily-item-lead" : ""}`}
                    key={item.id}
                  >
                    <div className="daily-item-meta">
                      <span>{item.kind}</span>
                      <span>{item.version}</span>
                      <span>
                        {item.scope === "abstract"
                          ? "Abstract only"
                          : item.scope === "excerpt"
                            ? "Source excerpt"
                            : "Metadata only"}
                      </span>
                      {data.saved.includes(item.id) && (
                        <span className="daily-saved">Saved</span>
                      )}
                    </div>
                    <h3>
                      <Link href={`/library/items/${item.id}`} prefetch={false}>
                        {item.title}
                      </Link>
                    </h3>
                    <p className="daily-item-change">{item.change}</p>
                    <details className="daily-reason">
                      <summary>Why this appeared</summary>
                      <p>
                        {item.reason} These are predeclared fixture matches, not
                        a learned relevance score.
                      </p>
                    </details>
                    <p className="daily-caveat">
                      <strong>Keep in mind</strong> {item.caveat}
                    </p>
                    <div className="daily-item-footer">
                      <span>
                        {item.source} · {item.published}
                      </span>
                      <div>
                        <Link
                          className="daily-link"
                          href={`/library/items/${item.id}`}
                          prefetch={false}
                        >
                          {index === 0 ? "Read & investigate" : "Open source"}{" "}
                          <span aria-hidden="true">→</span>
                        </Link>
                        <button
                          className="daily-text-button"
                          aria-label={`${data.saved.includes(item.id) ? "Unsave" : "Save"} ${item.title}`}
                          aria-pressed={data.saved.includes(item.id)}
                          onClick={() =>
                            update((d) => ({
                              ...d,
                              saved: d.saved.includes(item.id)
                                ? d.saved.filter((id) => id !== item.id)
                                : [...d.saved, item.id],
                            }))
                          }
                        >
                          {data.saved.includes(item.id) ? "Unsave" : "Save"}
                          <span className="sr-only"> {item.title}</span>
                        </button>
                      </div>
                    </div>
                  </article>
                ))
              )}
              <div className="daily-edition-end">
                <span>That’s the shortlist. The rest can wait.</span>
                <button
                  className="daily-secondary"
                  onClick={() => update((d) => ({ ...d, done: !d.done }))}
                >
                  {data.done ? "Reopen today’s briefing" : "Done for today"}
                </button>
                <Announcement>
                  {data.done
                    ? "Edition marked done in this browser. Your saved items and questions are still here."
                    : "Read at your pace. Nothing is automatically marked understood."}
                </Announcement>
              </div>
            </section>
          )}
        </div>
        <aside className="daily-context" aria-label="Continue your research">
          <span className="daily-eyebrow">Keep the thread</span>
          <h2>
            A question worth
            <br />
            coming back to.
          </h2>
          {last ? (
            <div className="daily-thread">
              <div>
                <span>Your {last.kind.replace("-", " ")}</span>
                <p>{last.body}</p>
              </div>
              <div>
                <span>Evidence</span>
                <Link
                  href={`/library/items/${last.itemId}#${last.anchor}`}
                  prefetch={false}
                >
                  {ITEMS.find((item) => item.id === last.itemId)?.title}
                </Link>
              </div>
              <div>
                <span>Continue</span>
                <p>Your words are saved separately from source material.</p>
                <Link
                  className="daily-link"
                  href={`/library/items/${last.itemId}#notes`}
                  prefetch={false}
                >
                  Reopen your reading <span aria-hidden="true">→</span>
                </Link>
              </div>
            </div>
          ) : (
            <div className="daily-thread">
              <div>
                <span>Your current question</span>
                <p>
                  {data.researchQuestion ||
                    "Add your research question in Interests."}
                </p>
              </div>
              <div>
                <span>Start with the source</span>
                <p>Inspect what is available, then pin your own question.</p>
                <Link
                  className="daily-link"
                  href="/library/items/corpus-shift"
                  prefetch={false}
                >
                  Open the reader <span aria-hidden="true">→</span>
                </Link>
              </div>
            </div>
          )}
          <div className="daily-generation">
            <span className="daily-eyebrow">On your terms</span>
            <p>
              Grounded summaries and guided deep dives are next. Model
              generation stays off until you approve its sources, settings and
              budget.
            </p>
          </div>
          <div className="daily-streams">
            {STREAMS.slice(1)
              .filter((stream) => data.streams.includes(stream.id))
              .map((stream) => (
                <div key={stream.id}>
                  <span className="daily-eyebrow">{stream.label}</span>
                  <p>{stream.detail}</p>
                  <small>Watch prepared · live intake off</small>
                </div>
              ))}
            <Link
              href="/interests#streams"
              prefetch={false}
              className="daily-link"
            >
              Edit research streams →
            </Link>
          </div>
          <Link className="daily-link" href="/library" prefetch={false}>
            Your saved work <span aria-hidden="true">→</span>
          </Link>
        </aside>
      </div>
    </>
  );
}
