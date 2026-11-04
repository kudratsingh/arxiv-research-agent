"use client";

import type { WorkspaceState } from "@/lib/workspace/api";

export function InterestCoverage({
  coverage,
  sources,
  draft,
}: {
  coverage: WorkspaceState["interest_coverage"];
  sources: WorkspaceState["sources"];
  draft: boolean;
}) {
  return (
    <section
      className="workspace-interest-coverage"
      aria-labelledby="interest-coverage-title"
    >
      <h2 id="interest-coverage-title">
        What these interests actually monitor
      </h2>
      <p className="daily-muted">
        These are the terms and sources configured for your saved interests.
        Broad catalogue navigation does not establish full literature coverage.
      </p>
      {draft && (
        <p className="workspace-version-notice">
          Your draft is not applied here yet. Save it to inspect its new
          matching terms and source coverage.
        </p>
      )}
      {coverage.length === 0 ? (
        <p className="daily-muted">
          No saved interest coverage is available yet.
        </p>
      ) : (
        coverage.map((interest) => (
          <details key={interest.topic_id} className="workspace-interest-row">
            <summary>
              <strong>{interest.label}</strong>
              <span className="workspace-topic-count">
                {interest.matching_mode === "browse_only"
                  ? "Browse only · no matching vocabulary"
                  : interest.status === "unconnected"
                    ? "Matching terms available · no connected source"
                    : "Matching terms configured · limited source scope"}
              </span>
            </summary>
            <p className="workspace-coverage-status"><strong>Check status:</strong> {interest.status.replaceAll("_", " ")} · {interest.matching_mode === "browse_only" ? "Browse-only navigation" : "Coverage remains bounded to configured sources"}</p>
            {interest.terms.length > 0 && (
              <p>
                <strong>Matches these terms:</strong>{" "}
                {interest.terms.join(", ")}
              </p>
            )}
            {interest.matching_mode === "descendant_terms" && (
              <p>
                Terms include {interest.descendant_ids.length} detailed
                descendant topics.
              </p>
            )}
            <p>
              <strong>Configured sources:</strong>{" "}
              {interest.source_ids.length
                ? interest.source_ids
                    .map(
                      (id) =>
                        sources.find((source) => source.source_id === id)
                          ?.name ?? id,
                    )
                    .join(", ")
                : "None for this selection"}
            </p>
            {interest.limitations.map((limitation) => (
              <p className="daily-muted" key={limitation}>
                {limitation}
              </p>
            ))}
          </details>
        ))
      )}
    </section>
  );
}
