"use client";

import { useEffect, useRef, useState } from "react";
import {
  errorMessage,
  requestId,
  workspaceRequest,
  type FakeDraft,
  type FakeJob,
  type FakeRequestPreview,
  type MaterialDocument,
  type MaterialInfo,
} from "@/lib/workspace/api";

const terminal = new Set([
  "ready",
  "ready_partial",
  "cancelled",
  "failed",
  "interrupted",
  "budget_stopped",
  "stale",
]);
function bytes(value: string) {
  return new TextEncoder().encode(value).length;
}

/** An explicitly invoked fixture pipeline. It never calls a paid model. */
export function SyntheticWorkbench({
  workId,
  versionId,
  announce,
  onSource,
}: {
  workId: string;
  versionId: string;
  announce: (message: string) => void;
  onSource: (anchor: string) => void;
}) {
  const [materials, setMaterials] = useState<MaterialInfo[] | null>(null);
  const [material, setMaterial] = useState<MaterialDocument | null>(null);
  const [kind, setKind] = useState<"summary" | "deep_dive">("summary");
  const [spanIds, setSpanIds] = useState<string[]>([]);
  const [includeQuestion, setIncludeQuestion] = useState(false);
  const [question, setQuestion] = useState("");
  const [preview, setPreview] = useState<FakeRequestPreview | null>(null);
  const [job, setJob] = useState<FakeJob | null>(null);
  const [history, setHistory] = useState<FakeJob[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const attempts = useRef(new Map<string, string>());
  const stop = useRef(false);
  const currentJob = useRef<FakeJob | null>(null);
  useEffect(() => {
    stop.current = false;
    return () => {
      stop.current = true;
    };
  }, []);
  const maxSpans = kind === "summary" ? 4 : 8,
    maxBytes = kind === "summary" ? 8000 : 16000;
  const selected =
    material?.spans.filter(
      (span) => spanIds.length === 0 || spanIds.includes(span.span_id),
    ) ?? [];
  const sourceBytes = selected.reduce(
    (total, span) => total + bytes(span.text),
    0,
  );
  const oversized = selected.length > maxSpans || sourceBytes > maxBytes;
  const input = {
    kind,
    material_ids: material ? [material.material_id] : [],
    span_ids: spanIds,
    question: includeQuestion ? question : "",
  };
  function clear() {
    setPreview(null);
    setJob(null);
    currentJob.current = null;
    setFailure("");
  }
  function failed(error: unknown) {
    const message = errorMessage(error);
    setFailure(message);
    announce(message);
  }
  async function loadMaterials() {
    setBusy(true);
    try {
      setMaterials(
        await workspaceRequest<MaterialInfo[]>(
          `materials?work_id=${encodeURIComponent(workId)}&version_id=${encodeURIComponent(versionId)}`,
        ),
      );
      setFailure("");
    } catch (error) {
      failed(error);
    } finally {
      setBusy(false);
    }
  }
  async function choose(id: string) {
    clear();
    setMaterial(null);
    setSpanIds([]);
    if (!id) return;
    setBusy(true);
    try {
      const value = await workspaceRequest<MaterialDocument>(
        `materials/${encodeURIComponent(id)}`,
      );
      if (value.work_id !== workId || value.version_id !== versionId)
        throw new Error(
          "retained material belongs to a different source version",
        );
      setMaterial(value);
    } catch (error) {
      failed(error);
    } finally {
      setBusy(false);
    }
  }
  async function inspectRequest() {
    setBusy(true);
    setFailure("");
    try {
      const value = await workspaceRequest<FakeRequestPreview>(
        "generation/preview",
        input,
      );
      setPreview(value);
      setJob(null);
      currentJob.current = null;
      announce(
        "Synthetic request preview ready. Inspect its exact source context and zero-dollar envelope before running.",
      );
    } catch (error) {
      setPreview(null);
      failed(error);
    } finally {
      setBusy(false);
    }
  }
  function update(value: FakeJob) {
    currentJob.current = value;
    setJob(value);
  }
  async function run() {
    if (!preview) return;
    setBusy(true);
    setFailure("");
    stop.current = false;
    const body = { ...input, expected_digest: preview.request_digest };
    const fingerprint = JSON.stringify(body),
      id = attempts.current.get(fingerprint) ?? requestId();
    attempts.current.set(fingerprint, id);
    try {
      let value = await workspaceRequest<FakeJob>("generation/jobs", {
        ...body,
        request_id: id,
      });
      attempts.current.delete(fingerprint);
      update(value);
      // An explicit foreground action has a bounded four-step envelope. There
      // is no timer, worker polling, or execution on navigation.
      for (
        let count = 0;
        count < 4 && !terminal.has(value.state) && !stop.current;
        count++
      ) {
        const before = value.revision;
        value = await workspaceRequest<FakeJob>(
          `generation/jobs/${value.id}/advance`,
          {},
        );
        if (stop.current) break;
        update(value);
        if (value.revision === before) break;
      }
      announce(
        stop.current
          ? "Synthetic run stopped. Inspect the retained checkpoint before continuing."
          : `Synthetic run state: ${value.state.replaceAll("_", " ")}. These fixture results do not measure model quality.`,
      );
    } catch (error) {
      failed(error);
    } finally {
      setBusy(false);
    }
  }
  async function action(action: "cancel" | "recover" | "inspect" | "advance") {
    const latest = currentJob.current;
    if (!latest) return;
    if (action === "cancel") stop.current = true;
    if (action !== "cancel") setBusy(true);
    try {
      const value = await workspaceRequest<FakeJob>(
        `generation/jobs/${latest.id}${action === "inspect" ? "" : `/${action}`}`,
        action === "inspect" ? undefined : {},
      );
      update(value);
      setFailure("");
      announce(
        `Synthetic checkpoint ${action === "inspect" ? "loaded" : action === "advance" ? "advanced once" : action === "recover" ? "recovered" : "cancelled"}: ${value.state.replaceAll("_", " ")}.`,
      );
    } catch (error) {
      failed(error);
    } finally {
      if (action !== "cancel") setBusy(false);
    }
  }
  async function loadHistory() {
    setBusy(true);
    try {
      const values = await workspaceRequest<FakeJob[]>("generation/jobs");
      setHistory(
        values.filter((candidate) => {
          const sources = candidate.request.sources;
          return (
            Array.isArray(sources) &&
            sources.some(
              (source: unknown) =>
                !!source &&
                typeof source === "object" &&
                "work_id" in source &&
                "version_id" in source &&
                source.work_id === workId &&
                source.version_id === versionId,
            )
          );
        }),
      );
      setFailure("");
    } catch (error) {
      failed(error);
    } finally {
      setBusy(false);
    }
  }
  const draft = job?.result?.draft ?? job?.draft;
  return (
    <section
      className="workspace-synthetic"
      aria-labelledby="synthetic-workbench-title"
    >
      <span className="daily-eyebrow">Synthetic · local fixture only · $0</span>
      <h3 id="synthetic-workbench-title">Inspect the analysis workflow.</h3>
      <p>
        This runs a deterministic fixture through source selection, draft, check
        and bounded repair. It is not a real summary or guided deep dive, and
        its checks do not establish factual quality. Paid generation remains
        disabled.
      </p>
      <p className="workspace-note-context">
        Only the retained material you select and an optional question you type
        below enter this request. Your notes, profile and reading history are
        excluded.
      </p>
      <div className="workspace-card-actions">
        <button
          className="daily-secondary"
          disabled={busy}
          onClick={() => void loadMaterials()}
        >
          Choose retained source context
        </button>
        <button
          className="daily-text-button"
          disabled={busy}
          onClick={() => void loadHistory()}
        >
          Load this version’s synthetic checkpoints
        </button>
      </div>
      {materials && materials.length === 0 && (
        <p>
          No retained text is available for a synthetic request. You can still
          read the source link and save your own notes.
        </p>
      )}
      {materials && materials.length > 0 && (
        <div className="workspace-form-stack">
          <label>
            Synthetic workflow
            <select
              disabled={busy}
              value={kind}
              onChange={(event) => {
                setKind(event.target.value as typeof kind);
                clear();
              }}
            >
              <option value="summary">Summary-shaped fixture</option>
              <option value="deep_dive">Deep-dive-shaped fixture</option>
            </select>
          </label>
          <label>
            Source context
            <select
              disabled={busy}
              value={material?.material_id ?? ""}
              onChange={(event) => void choose(event.target.value)}
            >
              <option value="">Select one retained material</option>
              {materials.map((value) => (
                <option key={value.material_id} value={value.material_id}>
                  {value.scope} ·{" "}
                  {value.page_numbers
                    ? `original pages ${value.page_numbers.join(", ")}`
                    : "retained text"}{" "}
                  · {value.quality}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {material && (
        <>
          <p className="workspace-note-context">
            Scope: {material.scope} ·{" "}
            {material.complete
              ? "complete retained extraction"
              : "partial extraction"}{" "}
            · {material.spans.length} retained passages · source{" "}
            {material.source_hash}
          </p>
          {material.warnings.map((warning) => (
            <p className="workspace-version-notice" key={warning}>
              {warning}
            </p>
          ))}
          <fieldset disabled={busy} className="workspace-span-picker">
            <legend>
              Choose passages, or leave all unchecked to request the whole
              retained material
            </legend>
            <p>
              {selected.length} selected passages ·{" "}
              {sourceBytes.toLocaleString()} UTF-8 source bytes. This workflow
              permits at most {maxSpans} passages and{" "}
              {maxBytes.toLocaleString()} bytes; oversize requests are refused,
              never silently truncated.
            </p>
            {material.spans.map((span) => (
              <label key={span.span_id}>
                <input
                  type="checkbox"
                  checked={spanIds.includes(span.span_id)}
                  onChange={(event) => {
                    setSpanIds(
                      event.target.checked
                        ? [...spanIds, span.span_id]
                        : spanIds.filter((id) => id !== span.span_id),
                    );
                    clear();
                  }}
                />{" "}
                <span>
                  {span.page === null
                    ? "Retained text"
                    : `Original page ${span.page}`}{" "}
                  · characters {span.start}–{span.end}
                  <br />
                  {Array.from(span.text).slice(0, 180).join("")}
                  {Array.from(span.text).length > 180 ? "…" : ""}
                </span>
              </label>
            ))}
          </fieldset>
          {oversized && (
            <p className="workspace-version-notice">
              Choose a smaller explicit passage set before previewing. The full
              retained material exceeds this workflow’s bound.
            </p>
          )}
          <label className="workspace-inline-checkbox">
            <input
              disabled={busy}
              type="checkbox"
              checked={includeQuestion}
              onChange={(event) => {
                setIncludeQuestion(event.target.checked);
                clear();
              }}
            />{" "}
            Include a question I type for this synthetic request
          </label>
          {includeQuestion && (
            <label>
              Optional request question
              <textarea
                rows={3}
                maxLength={4000}
                disabled={busy}
                value={question}
                onChange={(event) => {
                  setQuestion(event.target.value);
                  clear();
                }}
              />
            </label>
          )}
          <button
            className="daily-secondary"
            disabled={busy || !selected.length || oversized}
            onClick={() => void inspectRequest()}
          >
            Preview exact synthetic request
          </button>
        </>
      )}
      {failure && (
        <p className="workspace-version-notice">
          The synthetic action did not complete. The last server checkpoint is
          retained; no real model was called. {failure}
        </p>
      )}
      {preview && (
        <div className="workspace-synthetic-preview">
          <h4>Exact synthetic request</h4>
          <p>
            {preview.model_id} · {preview.fixture_revision} · maximum{" "}
            {preview.limits.max_calls} fixture calls,{" "}
            {preview.limits.max_repairs} repair · actual model spend $
            {preview.actual_usd}
          </p>
          <p>
            {preview.usage_basis}. These counters are not a model price
            estimate.
          </p>
          <p className="workspace-origin">Digest {preview.request_digest}</p>
          <details open>
            <summary className="daily-link">
              Inspect request JSON and permitted context
            </summary>
            <pre
              className="workspace-receipt"
              role="region"
              aria-label="Exact synthetic request JSON"
              tabIndex={0}
            >
              {JSON.stringify(preview.request, null, 2)}
            </pre>
          </details>
          <button
            className="daily-button"
            disabled={busy || !!job}
            onClick={() => void run()}
          >
            Run synthetic workflow · $0
          </button>
        </div>
      )}
      {history && (
        <div className="workspace-form-stack">
          <h4>Retained synthetic checkpoints for this version</h4>
          {history.length === 0 ? (
            <p>No synthetic checkpoints are retained for this version.</p>
          ) : (
            history.map((value) => (
              <button
                key={value.id}
                className="daily-text-button"
                disabled={busy}
                onClick={() => {
                  update(value);
                  setPreview(null);
                  setFailure("");
                }}
              >
                {value.kind.replaceAll("_", " ")} ·{" "}
                {value.state.replaceAll("_", " ")} · {value.id}
              </button>
            ))
          )}
        </div>
      )}
      {job && (
        <section
          className="workspace-synthetic-result"
          aria-labelledby="synthetic-checkpoint-title"
        >
          <h4 id="synthetic-checkpoint-title">
            Synthetic checkpoint · {job.state.replaceAll("_", " ")}
          </h4>
          <p className="workspace-origin">
            {job.id} · revision {job.revision}
            {job.cached
              ? " · identical synthetic result reused from cache"
              : ""}
          </p>
          {job.error && (
            <p className="workspace-version-notice">Stopped: {job.error}</p>
          )}
          {job.cancel_requested && (
            <p>
              Cancellation requested; inspect the checkpoint to confirm its
              state.
            </p>
          )}
          <div className="workspace-card-actions">
            <button
              className="daily-text-button"
              disabled={busy}
              onClick={() => void action("inspect")}
            >
              Reload checkpoint
            </button>
            {!terminal.has(job.state) && (
              <button
                className="daily-secondary"
                onClick={() => void action("cancel")}
              >
                Cancel synthetic run
              </button>
            )}
            {!busy && !terminal.has(job.state) && (
              <button
                className="daily-secondary"
                onClick={() => void action("advance")}
              >
                Advance one synthetic step
              </button>
            )}
            {["drafting", "checking", "repairing", "interrupted"].includes(
              job.state,
            ) && (
              <button
                className="daily-secondary"
                disabled={busy}
                onClick={() => void action("recover")}
              >
                Recover expired checkpoint
              </button>
            )}
          </div>
          <dl className="workspace-usage">
            <div>
              <dt>Workflow counters</dt>
              <dd>
                {job.usage.workflow.input_tokens} in /{" "}
                {job.usage.workflow.output_tokens} out
              </dd>
            </div>
            <div>
              <dt>Checker counters</dt>
              <dd>
                {job.usage.checker.input_tokens} in /{" "}
                {job.usage.checker.output_tokens} out
              </dd>
            </div>
            <div>
              <dt>Unknown counters</dt>
              <dd>
                {job.usage.unknown.input_tokens} in /{" "}
                {job.usage.unknown.output_tokens} out
              </dd>
            </div>
            <div>
              <dt>Fixture calls / actual spend</dt>
              <dd>
                {job.usage.used_calls} / {job.usage.max_calls} · $
                {job.usage.actual_usd}
              </dd>
            </div>
          </dl>
          <p className="workspace-note-context">
            {job.usage.usage_basis}. Workflow, checker and unknown counters stay
            separate.
          </p>
          {draft && <SyntheticDraft draft={draft} onSource={onSource} />}
          {job.grounding && (
            <details>
              <summary className="daily-link">
                Synthetic check diagnostics · not a quality score
              </summary>
              <pre
                className="workspace-receipt"
                role="region"
                aria-label="Synthetic check diagnostics"
                tabIndex={0}
              >
                {JSON.stringify(job.grounding, null, 2)}
              </pre>
            </details>
          )}
          {job.result && (
            <p className="workspace-version-notice">
              {job.result.check_basis}. This result has not qualified a real
              model or calibrated judge.
            </p>
          )}
        </section>
      )}
    </section>
  );
}

function SyntheticDraft({
  draft,
  onSource,
}: {
  draft: FakeDraft;
  onSource: (anchor: string) => void;
}) {
  return (
    <div className="workspace-synthetic-draft">
      <span className="daily-eyebrow">
        Synthetic output · do not treat as research findings
      </span>
      <h4>{draft.title}</h4>
      {Object.entries(draft.sections).map(([title, ids]) => (
        <section key={title}>
          <h5>{title.replaceAll("_", " ")}</h5>
          {ids.map((id) => {
            const claim = draft.claims.find(
              (candidate) => candidate.claim_id === id,
            )!;
            return (
              <article key={id}>
                <span className="workspace-note-context">
                  {claim.kind === "inference"
                    ? `Inference · ${claim.inference_label || "unverified proposal"}`
                    : "Fixture quotation-shaped claim"}
                </span>
                <p>{claim.text}</p>
                {claim.evidence.map((evidence) => (
                  <button
                    key={evidence.span_id}
                    className="daily-text-button"
                    onClick={() =>
                      onSource(
                        evidence.page === null
                          ? `${evidence.scope}:${evidence.start}:${evidence.end}`
                          : `material:${evidence.material_id}:page:${evidence.page}:${evidence.start}:${evidence.end}`,
                      )
                    }
                  >
                    Inspect retained evidence ·{" "}
                    {evidence.page === null
                      ? evidence.scope
                      : `original page ${evidence.page}`}{" "}
                    · {evidence.start}–{evidence.end}
                  </button>
                ))}
              </article>
            );
          })}
        </section>
      ))}
      {draft.questions.length > 0 && (
        <div>
          <h5>Fixture questions</h5>
          <ul>
            {draft.questions.map((value) => (
              <li key={value}>{value}</li>
            ))}
          </ul>
        </div>
      )}
      {draft.proposed_actions.length > 0 && (
        <div>
          <h5>Proposed actions · untested</h5>
          <ul>
            {draft.proposed_actions.map((value) => (
              <li key={value}>{value}</li>
            ))}
          </ul>
        </div>
      )}
      {draft.limitations.map((value) => (
        <p className="workspace-note-context" key={value}>
          {value}
        </p>
      ))}
    </div>
  );
}
