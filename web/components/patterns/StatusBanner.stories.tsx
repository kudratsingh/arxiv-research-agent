/**
 * Patterns/StatusBanner — WO-12 criteria 4, 5 and 6, on screen.
 *
 * READ `AllFailures` FIRST. It is one story per `ApiFailure.kind` — all
 * twelve the normalizer can produce (04 §3.4) — rendered from the
 * dictionary rather than from anything typed here, which is the point:
 * every sentence on this page came out of `describeFailure()`, so what a
 * reviewer sees in Storybook is exactly what a surface will render.
 *
 * `RateLimitedRetryAfter` is the 429 that consumes the header, beside the
 * 429 that has none. `Unauthorized` is the 401, and it is the one to check
 * against 03 §6: it reads as a **server configuration** message and offers
 * no sign-in, because there is no user identity to re-authenticate.
 *
 * `UnmappedErrorType` is criterion 6's fall-through. It shows the generic
 * sentence AND the raw `error` text, which is what stops an unmapped value
 * from being swallowed. `MappedErrorTypes` is the other nine.
 *
 * `ForcedColours` is where the RC-17 claim is checked: five severities on
 * four hues, told apart by five words and five marks, with the hue taken
 * away entirely.
 *
 * TWO DELIBERATE IMPORT CHOICES, both about the Storybook project's
 * coverage rather than about taste. This file imports `ApiFailure` as a
 * TYPE and takes the twelve kinds from `FAILURE_COPY`'s own keys, so
 * loading a story does not drag `lib/api`'s client into a run that never
 * calls it; and it reads only `lib/copy/errors`, which is the module these
 * stories actually exercise. `web/tests/copy/StatusBanner.test.tsx` pins
 * `FAILURE_COPY`'s key set to `API_FAILURE_KINDS`, so nothing is lost by
 * not importing the constant here.
 *
 * NO STRING IN THIS FILE IS RENDERED AS TEXT. `copy/no-inline-text` covers
 * components/patterns/**, stories included; the section headings below are
 * documentation chrome passed as props, which the rule leaves alone by
 * design.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactNode } from "react";

import {
  ERROR_TYPE_COPY,
  FAILURE_COPY,
  MAPPED_ERROR_TYPES,
  SEVERITY_WORD,
  describeErrorType,
  describeFailure,
  rawErrorEvidence,
} from "@/lib/copy/errors";
import type { ApiFailure } from "@/lib/api";
import { STATUS_SEVERITY_ROLE, type StatusSeverity } from "@/lib/tokens";

import { StatusBanner } from "./StatusBanner";

const meta = {
  title: "Patterns/StatusBanner",
  component: StatusBanner,
  args: {
    severity: "critical" as StatusSeverity,
    sentence: FAILURE_COPY.server_error.sentence,
  },
} satisfies Meta<typeof StatusBanner>;

export default meta;
type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// The twelve failures, as the normalizer produces them.
// ---------------------------------------------------------------------------

/** One recorded-shaped body per kind (04 §3.4's table of observed shapes). */
const FAILURES: Record<ApiFailure["kind"], ApiFailure> = {
  unauthorized: {
    kind: "unauthorized",
    status: 401,
    message: "",
    raw: { detail: "missing_api_key" },
  },
  not_found: {
    kind: "not_found",
    status: 404,
    message: "",
    raw: { detail: "job_not_found" },
  },
  conflict: {
    kind: "conflict",
    status: 409,
    state: "running",
    message: "",
    raw: { detail: "job_not_awaiting_review (status=running)" },
  },
  rate_limited: {
    kind: "rate_limited",
    status: 429,
    retryAfterSec: 60,
    message: "",
    raw: { detail: { error: "rate_limited", key_id: "shared" } },
  },
  validation: {
    kind: "validation",
    status: 422,
    fields: [{ path: "query", message: "String should have at most 8000 characters" }],
    message: "",
    raw: { detail: [] },
  },
  upstream_unavailable: {
    kind: "upstream_unavailable",
    status: 502,
    message: "",
    raw: { detail: "api_upstream_unavailable" },
  },
  proxy_misconfigured: {
    kind: "proxy_misconfigured",
    status: 503,
    message: "",
    raw: { detail: "api_proxy_misconfigured" },
  },
  server_error: { kind: "server_error", status: 500, message: "", raw: null },
  offline: { kind: "offline", message: "", raw: new TypeError("Failed to fetch") },
  timeout: { kind: "timeout", message: "", raw: null },
  cancelled: { kind: "cancelled", message: "", raw: null },
  unknown: { kind: "unknown", status: null, message: "", raw: null },
};

/** The twelve, in the union's own order. Pinned to `API_FAILURE_KINDS` by test. */
const KINDS = Object.keys(FAILURE_COPY) as Array<ApiFailure["kind"]>;

/** The 429 that carried a `Retry-After` and an hourly ceiling. */
const RATE_LIMITED_WITH_HEADER: ApiFailure = {
  kind: "rate_limited",
  status: 429,
  retryAfterSec: 900,
  limitPerHour: 20,
  message: "",
  raw: { detail: { error: "rate_limited", key_id: "shared", limit_per_hour: 20 } },
};

function Failure({
  failure,
  userTriggered = false,
}: {
  failure: ApiFailure;
  userTriggered?: boolean;
}) {
  return <StatusBanner {...describeFailure(failure)} userTriggered={userTriggered} />;
}

function Section({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-ui-xs font-semibold uppercase text-ink-muted">{heading}</h2>
      <div className="flex flex-col gap-3">{children}</div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Criterion 4 — five severities, four roles, five words, five marks.
// ---------------------------------------------------------------------------

const SEVERITIES = Object.keys(STATUS_SEVERITY_ROLE) as StatusSeverity[];

export const Severities: Story = {
  render: () => (
    <div className="flex flex-col gap-3 p-6">
      {SEVERITIES.map((severity) => (
        <StatusBanner
          key={severity}
          severity={severity}
          sentence={FAILURE_COPY.not_found.sentence}
          recovery={SEVERITY_WORD[severity]}
        />
      ))}
    </div>
  ),
};

/** RC-17's claim, with the hue removed: the words and the marks still differ. */
export const ForcedColours: Story = {
  ...Severities,
  globals: { theme: "forced-colors" },
};

export const Dark: Story = { ...Severities, globals: { theme: "dark" } };

/**
 * The live-region rule (03 §7.3). Only the user-triggered failure is a
 * `role="alert"`; the ambient one beside it is ordinary content, and
 * neither is a second `role="status"` region.
 */
export const LiveRegions: Story = {
  render: () => (
    <div className="flex flex-col gap-6 p-6">
      <Section heading="User-triggered failure — role=alert">
        <Failure failure={FAILURES.rate_limited} userTriggered />
      </Section>
      <Section heading="Became true on its own — ordinary content">
        <Failure failure={FAILURES.not_found} />
      </Section>
    </div>
  ),
};

/** The mark override, for a state whose shape is not its severity's default. */
export const OverriddenMark: Story = {
  render: () => (
    <StatusBanner
      severity="info"
      word={FAILURE_COPY.not_found.word}
      mark="dashed-square"
      sentence={FAILURE_COPY.not_found.sentence}
      recovery={FAILURE_COPY.not_found.recovery}
    />
  ),
};

// ---------------------------------------------------------------------------
// Criterion 5 — one story per kind, twelve of them.
// ---------------------------------------------------------------------------

export const Unauthorized: Story = { render: () => <Failure failure={FAILURES.unauthorized} /> };
export const NotFound: Story = { render: () => <Failure failure={FAILURES.not_found} /> };
export const Conflict: Story = { render: () => <Failure failure={FAILURES.conflict} /> };
export const RateLimited: Story = {
  render: () => <Failure failure={FAILURES.rate_limited} userTriggered />,
};
/** The 429 that consumes `Retry-After` and the body's `limit_per_hour`. */
export const RateLimitedRetryAfter: Story = {
  render: () => <Failure failure={RATE_LIMITED_WITH_HEADER} userTriggered />,
};
export const Validation: Story = {
  render: () => <Failure failure={FAILURES.validation} userTriggered />,
};
export const UpstreamUnavailable: Story = {
  render: () => <Failure failure={FAILURES.upstream_unavailable} />,
};
/** The name §4's state-coverage map uses for row F's 502. */
export const UpstreamDown: Story = {
  render: () => <Failure failure={FAILURES.upstream_unavailable} />,
};
export const ProxyMisconfigured: Story = {
  render: () => <Failure failure={FAILURES.proxy_misconfigured} />,
};
export const ServerError: Story = { render: () => <Failure failure={FAILURES.server_error} /> };
export const Offline: Story = { render: () => <Failure failure={FAILURES.offline} /> };
export const Timeout: Story = { render: () => <Failure failure={FAILURES.timeout} /> };
export const Cancelled: Story = { render: () => <Failure failure={FAILURES.cancelled} /> };
export const Unknown: Story = { render: () => <Failure failure={FAILURES.unknown} /> };

/** All twelve at once, in the union's order. */
export const AllFailures: Story = {
  render: () => (
    <div className="flex flex-col gap-3 p-6">
      {KINDS.map((kind) => (
        <Failure key={kind} failure={FAILURES[kind]} />
      ))}
    </div>
  ),
};

// ---------------------------------------------------------------------------
// Criterion 6 — the nine mapped values, and the visible fall-through.
// ---------------------------------------------------------------------------

const RAW_MESSAGE = "SomeFutureExceptionName: unexpected empty synthesis buffer";

export const MappedErrorTypes: Story = {
  render: () => (
    <div className="flex flex-col gap-3 p-6">
      {MAPPED_ERROR_TYPES.map((errorType) => {
        const described = describeErrorType(errorType, ERROR_TYPE_COPY[errorType].sentence);
        return (
          <StatusBanner
            key={errorType}
            severity="critical"
            word={FAILURE_COPY.server_error.word}
            sentence={described.sentence}
            recovery={described.recovery}
            evidence={rawErrorEvidence(described.errorType, described.rawError)}
          />
        );
      })}
    </div>
  ),
};

/**
 * 03 §2.2 row 15 and §8.3's *anything else*: the generic sentence AND the
 * raw `error` text, visible without opening anything.
 */
export const UnmappedErrorType: Story = {
  render: () => {
    const described = describeErrorType("SomeFutureExceptionName", RAW_MESSAGE);
    return (
      <StatusBanner
        severity="critical"
        word={FAILURE_COPY.server_error.word}
        sentence={described.sentence}
        recovery={described.recovery}
        evidence={rawErrorEvidence(described.errorType, described.rawError)}
      />
    );
  },
};

/** An `error_type` the backend did not report at all. Still not "unknown". */
export const ErrorTypeNotReported: Story = {
  render: () => {
    const described = describeErrorType(null, null);
    return (
      <StatusBanner
        severity="critical"
        word={FAILURE_COPY.server_error.word}
        sentence={described.sentence}
        recovery={described.recovery}
        evidence={rawErrorEvidence(described.errorType, described.rawError)}
      />
    );
  },
};
