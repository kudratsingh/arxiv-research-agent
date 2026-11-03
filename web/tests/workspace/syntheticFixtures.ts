import type {
  FakeDraft,
  FakeJob,
  FakeRequestPreview,
} from "@/lib/workspace/api";
import { work } from "./fixtures";
import { MAT, SPAN } from "./materialFixtures";
export const JOB = "fake-test-job";
export function draft(): FakeDraft {
  return {
    kind: "summary",
    title: "Synthetic quotation and an untested proposal",
    claims: [
      {
        claim_id: "quote",
        text: "A retrieval result on the original page.",
        kind: "factual",
        required_scope: "excerpt",
        required_section: null,
        inference_label: null,
        evidence: [
          {
            material_id: MAT,
            span_id: SPAN,
            work_id: work().work_id,
            version_id: work().version_id,
            source_hash: "source-sha",
            scope: "excerpt",
            parser_revision: "pdf-safe-v1",
            page: 3,
            start: 2,
            end: 13,
            quote: "A retrieval",
          },
        ],
      },
      {
        claim_id: "proposal",
        text: "Compare a fixed baseline before changing the system.",
        kind: "inference",
        required_scope: "abstract",
        required_section: null,
        inference_label: "proposal, not verified",
        evidence: [],
      },
    ],
    sections: { overview: ["quote", "proposal"] },
    questions: ["Which condition needs a follow-up?"],
    proposed_actions: ["Write a bounded test."],
    limitations: ["Fixture output is not evidence of model quality."],
  };
}
export function preview(): FakeRequestPreview {
  return {
    mode: "fake",
    model_id: "fixture-workspace-v1",
    fixture_revision: "workspace-executor-v1",
    kind: "summary",
    request_digest: "digest-exact-context",
    request: {
      sources: [
        {
          material_id: MAT,
          work_id: work().work_id,
          version_id: work().version_id,
        },
      ],
      private_context: { notes: false, profile: false, reading_history: false },
    },
    limits: {
      max_calls: 4,
      max_repairs: 1,
      per_call_input_tokens: 64000,
      per_call_output_tokens: 32000,
      max_input_tokens: 256000,
      max_output_tokens: 128000,
      max_source_bytes: 8000,
      max_spans: 4,
    },
    usage_basis: "simulated UTF-8 byte counters; not provider tokens",
    actual_usd: "0.000000",
  };
}
export function job(state: FakeJob["state"] = "queued", revision = 1): FakeJob {
  return {
    id: JOB,
    kind: "summary",
    state,
    revision,
    mode: "fake",
    model_id: "fixture-workspace-v1",
    fixture_revision: "workspace-executor-v1",
    request_digest: preview().request_digest,
    request: preview().request,
    draft: state === "ready" ? draft() : null,
    grounding: state === "ready" ? { supported: 1, abstained: 0 } : null,
    result:
      state === "ready"
        ? {
            mode: "fake",
            model_id: "fixture-workspace-v1",
            fixture_revision: "workspace-executor-v1",
            check_basis:
              "synthetic exact-quotation checks; not a calibrated judge or model-quality result",
            request_digest: preview().request_digest,
            draft: draft(),
            grounding: { supported: 1 },
          }
        : null,
    steps: [],
    usage: {
      workflow: { input_tokens: 1200, output_tokens: 300 },
      checker: { input_tokens: 400, output_tokens: 50 },
      unknown: { input_tokens: 0, output_tokens: 0 },
      used_calls: revision - 1,
      max_calls: 4,
      usage_basis: "simulated UTF-8 byte counters; not provider tokens",
      actual_usd: "0.000000",
    },
    cancel_requested: false,
    lease_until: null,
    error: null,
    cached: false,
  };
}
