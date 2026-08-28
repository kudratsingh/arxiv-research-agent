/**
 * Features/QueryComposer — WO-13 criterion 9's ten states.
 *
 * `Empty` `Filled` `NearLimit` `OverLimit` `Submitting` `RateLimited`
 * `Unauthorized` `UpstreamDown` `ProxyMisconfigured` `FollowUp`, each one
 * reached by passing props and nothing else. That is the point of the
 * component being data-free (see `QueryComposer.tsx`'s header): no MSW, no
 * provider, no `?job=`, and — since `POST /research` is the one call in
 * this product that costs money — no possibility of a story buying a run.
 *
 * IMPORT HYGIENE, DELIBERATE. `vitest.config.mts` records the measurement
 * hazard for WO-13 … WO-19: a module loaded by BOTH Vitest projects has its
 * function lists concatenated, so a story that drags in a module it barely
 * exercises inflates the denominator for free. This file therefore imports
 * the component, one constant from `lib/copy/composer` (already in the
 * component's own graph, and deliberately NOT `lib/copy/run`, which is the
 * spine's and the metrics strip's dictionary), and `ApiFailure` as a TYPE —
 * which is erased, so `lib/api`'s client never enters the Storybook project
 * at all.
 *
 * NO STRING HERE IS RENDERED AS TEXT. `copy/no-inline-text` covers
 * `components/features/**`, stories included. The literals below are
 * `ApiFailure` field values — a wire shape, not copy — and the sentences
 * the stories display all come out of `lib/copy/errors` inside the
 * component.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { MAX_QUERY_LEN } from "@/lib/copy/composer";
import type { ApiFailure } from "@/lib/api";

import { NEAR_LIMIT_RATIO, QueryComposer } from "./QueryComposer";

const QUESTION =
  "How do current systems evaluate faithfulness in retrieval-augmented generation, and which of those measures survive a change of retriever?";

/** Long enough for the counter to warn, short enough to still be sendable. */
const NEAR = QUESTION.repeat(
  Math.ceil((MAX_QUERY_LEN * NEAR_LIMIT_RATIO) / QUESTION.length),
).slice(0, MAX_QUERY_LEN - 40);

/** Over the bound by a visible margin, so the refusal names a real number. */
const OVER = QUESTION.repeat(
  Math.ceil((MAX_QUERY_LEN + 200) / QUESTION.length),
).slice(0, MAX_QUERY_LEN + 137);

/** Recorded 4xx/5xx shapes, from 04 §3.4's table of what the API answers. */
const RATE_LIMITED: ApiFailure = {
  kind: "rate_limited",
  status: 429,
  retryAfterSec: 900,
  limitPerHour: 20,
  message: "",
  raw: { detail: { error: "rate_limited", key_id: "shared", limit_per_hour: 20 } },
};

const UNAUTHORIZED: ApiFailure = {
  kind: "unauthorized",
  status: 401,
  message: "",
  raw: { detail: "missing_api_key" },
};

const UPSTREAM_DOWN: ApiFailure = {
  kind: "upstream_unavailable",
  status: 502,
  message: "",
  raw: { detail: "api_upstream_unavailable" },
};

const PROXY_MISCONFIGURED: ApiFailure = {
  kind: "proxy_misconfigured",
  status: 503,
  message: "",
  raw: { detail: "api_proxy_misconfigured" },
};

const VALIDATION: ApiFailure = {
  kind: "validation",
  status: 422,
  fields: [{ path: "query", message: "String should have at most 8000 characters" }],
  message: "",
  raw: { detail: [] },
};

const meta = {
  title: "Features/QueryComposer",
  component: QueryComposer,
  args: {
    variant: "landing",
    // A story never submits: `POST /research` is the one billable call on
    // the surface, and the composer's whole state set is prop-reachable.
    onSubmit: () => undefined,
  },
  decorators: [
    (Story: () => React.ReactElement) => (
      <div className="w-full max-w-content p-6">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof QueryComposer>;

export default meta;
type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// The composer's own states (03 §4.3).
// ---------------------------------------------------------------------------

/** 03 §2.2 row 1. The counter is visible at zero characters (criterion 2). */
export const Empty: Story = {};

export const Filled: Story = { args: { value: QUESTION } };

/** The counter warns before the bound, in the review hue. */
export const NearLimit: Story = { args: { value: NEAR } };

/**
 * Over 8,000. Submit is refused client-side, the counter is critical, the
 * field is `aria-invalid`, and the text is still all there — the primitive
 * refuses rather than truncating.
 */
export const OverLimit: Story = { args: { value: OVER } };

/** `POST /research` is in flight: 03 §1.4's pending label, click refused. */
export const Submitting: Story = { args: { value: QUESTION, pending: true } };

/**
 * 03 §2.2 row 4. Not a bare `disabled` button: `aria-disabled` keeps the
 * control focusable and `aria-describedby` carries the reason.
 */
export const Unreachable: Story = {
  args: { value: QUESTION, unreachable: UPSTREAM_DOWN },
};

// ---------------------------------------------------------------------------
// Submission failures (03 §2.2 rows 17, 18, 19, 20). The question is kept
// in every one of them, and none of them offers an automatic retry (H6).
// ---------------------------------------------------------------------------

export const RateLimited: Story = {
  args: { value: QUESTION, failure: RATE_LIMITED },
};

export const Unauthorized: Story = {
  args: { value: QUESTION, failure: UNAUTHORIZED },
};

export const UpstreamDown: Story = {
  args: { value: QUESTION, failure: UPSTREAM_DOWN },
};

export const ProxyMisconfigured: Story = {
  args: { value: QUESTION, failure: PROXY_MISCONFIGURED },
};

/** Row 20: the 422 mapped onto the question field rather than swallowed. */
export const Validation: Story = {
  args: { value: QUESTION, failure: VALIDATION },
};

/**
 * H7. The thread was created before `POST /research` failed, so it exists,
 * it is empty, and it is offered rather than left to be found.
 */
export const FailedWithOrphanThread: Story = {
  args: {
    value: QUESTION,
    failure: RATE_LIMITED,
    orphanThreadHref: "/c/9f1c0d3e-0f3a-4f5f-9a1c-1b2c3d4e5f60",
  },
};

// ---------------------------------------------------------------------------
// The second variant, and the theme sweep.
// ---------------------------------------------------------------------------

/** 03 §4.3's compact variant: no display heading, no process strip. */
export const FollowUp: Story = {
  args: { variant: "follow-up", value: QUESTION },
};

export const Dark: Story = { args: { value: QUESTION }, globals: { theme: "dark" } };

export const ForcedColours: Story = {
  args: { value: QUESTION, failure: RATE_LIMITED },
  globals: { theme: "forced-colors" },
};

/** RC-14's narrowest width: the disclosure stays above the button. */
export const Narrow: Story = {
  args: { value: QUESTION },
  globals: { viewport: { value: "w320" } },
};
