/**
 * WO-12 criteria 4 and 5 — `StatusBanner`.
 *
 *   4. "Five severities mapped to existing roles per RC-17, each with a
 *      distinct word and mark. `role="alert"` ONLY for user-triggered
 *      failures; everything else is ordinary content or the single
 *      `role="status"` region."
 *   5. "One story per `ApiFailure.kind` — twelve — plus the 429 variant
 *      that consumes `Retry-After`, and the 401 that reads as a server
 *      configuration message, never a login prompt."
 *
 * RC-17'S CLAIM IS THE INTERESTING ONE. Five severities, four roles: the
 * palette ships no `warning` hue, so `warning` and `review` resolve to the
 * same colour. That is only acceptable because colour is the THIRD signal.
 * The tests below take the hue away — first by asserting the five words and
 * five marks are distinct, then by stripping every class off the rendered
 * tree — and check that the five are still told apart.
 *
 * THE LIVE-REGION RULE IS TESTED AS AN ABSENCE AS WELL AS A PRESENCE.
 * 03 §7.3 allows exactly two live regions product-wide, and the
 * `role="status"` one belongs to the trace spine. So there is a test that
 * no configuration of this component can produce one.
 */

import { describe, expect, it, vi } from "vitest";

import { SEVERITY_MARK } from "@/components/primitives/StatusBadge";
import { ALERT_SEVERITIES, StatusBanner } from "@/components/patterns/StatusBanner";
import { API_FAILURE_KINDS, type ApiFailure } from "@/lib/api";
import {
  FAILURE_COPY,
  SEVERITY_WORD,
  describeErrorType,
  describeFailure,
  rawErrorEvidence,
} from "@/lib/copy/errors";
import { UNAVAILABLE_COPY } from "@/lib/copy/run";
import { STATUS_SEVERITY_ROLE, type StatusSeverity } from "@/lib/tokens";

import { render, screen } from "../support/render";

const SEVERITIES = Object.keys(STATUS_SEVERITY_ROLE) as StatusSeverity[];

// ---------------------------------------------------------------------------
// Criterion 4 — severity, word, mark, role.
// ---------------------------------------------------------------------------

describe("criterion 4 — five severities on existing roles (RC-17)", () => {
  it("has exactly five", () => {
    expect(SEVERITIES).toEqual(["info", "review", "live", "warning", "critical"]);
  });

  it.each(SEVERITIES)("%s resolves to the role web/lib/tokens.ts assigns", (severity) => {
    const { container } = render(
      <StatusBanner severity={severity} sentence={UNAVAILABLE_COPY} />,
    );
    const banner = container.firstElementChild;
    expect(banner).toHaveAttribute("data-severity", severity);
    expect(banner).toHaveAttribute("data-role", STATUS_SEVERITY_ROLE[severity]);
  });

  it("invents no hue: four roles carry five severities", () => {
    const roles = new Set(SEVERITIES.map((severity) => STATUS_SEVERITY_ROLE[severity]));
    expect(roles.size).toBe(4);
    // RC-17 by name: `review` and `warning` share the review hue.
    expect(STATUS_SEVERITY_ROLE.warning).toBe(STATUS_SEVERITY_ROLE.review);
    expect(roles.has("success" as never)).toBe(false);
  });

  it("gives each severity a distinct word and a distinct mark", () => {
    // This is what does the work when the hue does not.
    const words = SEVERITIES.map((severity) => SEVERITY_WORD[severity]);
    const marks = SEVERITIES.map((severity) => SEVERITY_MARK[severity]);
    expect(new Set(words).size).toBe(5);
    expect(new Set(marks).size).toBe(5);
  });

  it.each(SEVERITIES)("renders %s's word and mark", (severity) => {
    const { container } = render(
      <StatusBanner severity={severity} sentence={UNAVAILABLE_COPY} />,
    );
    expect(screen.getByText(SEVERITY_WORD[severity])).toBeInTheDocument();
    expect(container.querySelector("svg")).toHaveAttribute(
      "data-mark",
      SEVERITY_MARK[severity],
    );
  });

  it("survives colour being removed entirely", () => {
    const { container } = render(
      <StatusBanner severity="warning" sentence={UNAVAILABLE_COPY} />,
    );
    for (const element of container.querySelectorAll("[class]")) {
      element.removeAttribute("class");
    }
    expect(screen.getByText(SEVERITY_WORD.warning)).toBeInTheDocument();
    expect(container.querySelector("svg")).toHaveAttribute(
      "data-mark",
      SEVERITY_MARK.warning,
    );
    expect(screen.getByText(UNAVAILABLE_COPY)).toBeInTheDocument();
  });

  it("takes a specific word over the severity's default", () => {
    render(
      <StatusBanner
        severity="info"
        word={FAILURE_COPY.not_found.word}
        sentence={UNAVAILABLE_COPY}
      />,
    );
    expect(screen.getByText(FAILURE_COPY.not_found.word)).toBeInTheDocument();
    expect(screen.queryByText(SEVERITY_WORD.info)).not.toBeInTheDocument();
  });
});

describe("criterion 4 — the live-region rule (03 §7.3)", () => {
  it("announces a user-triggered failure", () => {
    render(
      <StatusBanner
        severity="critical"
        sentence={FAILURE_COPY.upstream_unavailable.sentence}
        userTriggered
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      FAILURE_COPY.upstream_unavailable.sentence,
    );
  });

  it("does not announce anything that merely became true", () => {
    const { container } = render(
      <StatusBanner severity="info" sentence={UNAVAILABLE_COPY} />,
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(container.firstElementChild).not.toHaveAttribute("role");
    expect(container.firstElementChild).toHaveAttribute(
      "data-user-triggered",
      "false",
    );
  });

  it("never produces a second role=status region, in any configuration", () => {
    // The one `role="status"` product-wide is the spine's status line
    // (WO-15). Two of them would announce twice and neither would be the
    // authority.
    for (const severity of SEVERITIES) {
      const { container, unmount } = render(
        <StatusBanner
          severity={severity}
          sentence={UNAVAILABLE_COPY}
          recovery={FAILURE_COPY.not_found.recovery}
          evidence={rawErrorEvidence("orphaned", "reclaimed")}
          userTriggered={ALERT_SEVERITIES.includes(severity)}
        />,
      );
      expect(container.querySelectorAll('[role="status"]')).toHaveLength(0);
      expect(container.querySelectorAll("[aria-live]")).toHaveLength(0);
      unmount();
    }
  });

  it("refuses to announce anything that is not a failure", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    for (const severity of ["info", "review", "live"] as StatusSeverity[]) {
      expect(() =>
        render(
          <StatusBanner severity={severity} sentence={UNAVAILABLE_COPY} userTriggered />,
        ),
      ).toThrow(/reserved for user-triggered failures/);
    }
    error.mockRestore();
  });

  it("allows exactly the two failure severities to announce", () => {
    expect([...ALERT_SEVERITIES].sort()).toEqual(["critical", "warning"]);
  });
});

// ---------------------------------------------------------------------------
// Criterion 5 — twelve kinds, the 429 variant, the 401.
// ---------------------------------------------------------------------------

const FAILURES: Record<ApiFailure["kind"], ApiFailure> = {
  unauthorized: { kind: "unauthorized", status: 401, message: "", raw: null },
  not_found: { kind: "not_found", status: 404, message: "", raw: null },
  conflict: { kind: "conflict", status: 409, state: "running", message: "", raw: null },
  rate_limited: {
    kind: "rate_limited",
    status: 429,
    retryAfterSec: 60,
    message: "",
    raw: null,
  },
  validation: {
    kind: "validation",
    status: 422,
    fields: [{ path: "query", message: "is too long" }],
    message: "",
    raw: null,
  },
  upstream_unavailable: {
    kind: "upstream_unavailable",
    status: 502,
    message: "",
    raw: null,
  },
  proxy_misconfigured: {
    kind: "proxy_misconfigured",
    status: 503,
    message: "",
    raw: null,
  },
  server_error: { kind: "server_error", status: 500, message: "", raw: null },
  offline: { kind: "offline", message: "", raw: null },
  timeout: { kind: "timeout", message: "", raw: null },
  cancelled: { kind: "cancelled", message: "", raw: null },
  unknown: { kind: "unknown", status: null, message: "", raw: null },
};

describe("criterion 5 — one rendering per ApiFailure.kind", () => {
  it("covers all twelve the normalizer can produce", () => {
    expect(API_FAILURE_KINDS).toHaveLength(12);
    expect(Object.keys(FAILURES).sort()).toEqual([...API_FAILURE_KINDS].sort());
    expect(Object.keys(FAILURE_COPY).sort()).toEqual([...API_FAILURE_KINDS].sort());
  });

  it.each(API_FAILURE_KINDS)("%s renders a word, a sentence and a recovery", (kind) => {
    const copy = describeFailure(FAILURES[kind]);
    const { unmount } = render(
      <StatusBanner {...copy} userTriggered={ALERT_SEVERITIES.includes(copy.severity)} />,
    );
    expect(screen.getByText(copy.word)).toBeInTheDocument();
    expect(screen.getByText(copy.sentence)).toBeInTheDocument();
    expect(screen.getByText(copy.recovery)).toBeInTheDocument();
    unmount();
  });

  it("translates the 409's wire status rather than echoing it", () => {
    const copy = describeFailure(FAILURES.conflict);
    expect(copy.sentence).toContain("running");
    expect(copy.sentence).not.toContain("job_not_awaiting_review");
    const parked = describeFailure({
      kind: "conflict",
      status: 409,
      state: "pending_review",
      message: "",
      raw: null,
    });
    expect(parked.sentence).toContain("waiting for your review");
    expect(parked.sentence).not.toContain("pending_review");
  });

  it("names the rejected field on a 422", () => {
    expect(describeFailure(FAILURES.validation).recovery).toBe("query: is too long.");
  });
});

describe("criterion 5 — the 429 consumes Retry-After", () => {
  it("uses the header's seconds, not a fixed sentence", () => {
    const short = describeFailure({
      kind: "rate_limited",
      status: 429,
      retryAfterSec: 30,
      message: "",
      raw: null,
    });
    const long = describeFailure({
      kind: "rate_limited",
      status: 429,
      retryAfterSec: 900,
      limitPerHour: 20,
      message: "",
      raw: null,
    });
    expect(short.recovery).toContain("about 30 seconds");
    expect(long.recovery).toContain("about 15 minutes");
    expect(long.recovery).toContain("20 requests an hour");
  });

  it("is a named state, not a generic error (03 §2.2 row 18)", () => {
    render(<StatusBanner {...describeFailure(FAILURES.rate_limited)} userTriggered />);
    expect(
      screen.getByText("This workspace has used its hourly research budget."),
    ).toBeInTheDocument();
  });

  it("guesses no remaining budget when the body carried no ceiling", () => {
    const copy = describeFailure(FAILURES.rate_limited);
    expect(copy.recovery).not.toMatch(/\d+ requests? an hour/);
  });
});

describe("criterion 5 — the 401 is a server-configuration message", () => {
  it("says the deployment is not accepting requests from this server", () => {
    render(<StatusBanner {...describeFailure(FAILURES.unauthorized)} userTriggered />);
    expect(
      screen.getByText("This deployment is not accepting requests from this server."),
    ).toBeInTheDocument();
  });

  it("offers no login, no account and nothing to re-authenticate", () => {
    const copy = describeFailure(FAILURES.unauthorized);
    const text = `${copy.word} ${copy.sentence} ${copy.recovery}`;
    expect(text).not.toMatch(/sign|log ?in|account|password|credential|authenticat/i);
    expect(text).toMatch(/server|deployment|operator/i);
  });
});

describe("criterion 5 — the stories exist, one per kind", () => {
  /** `rate_limited` → `RateLimited`. */
  function storyName(kind: string): string {
    return kind
      .split("_")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join("");
  }

  it.each(API_FAILURE_KINDS)("exports a %s story", async (kind) => {
    const stories = await import("@/components/patterns/StatusBanner.stories");
    expect(Object.keys(stories)).toContain(storyName(kind));
  });

  it("exports the 429 Retry-After variant beside the plain 429", async () => {
    const stories = await import("@/components/patterns/StatusBanner.stories");
    expect(Object.keys(stories)).toContain("RateLimited");
    expect(Object.keys(stories)).toContain("RateLimitedRetryAfter");
  });

  it("exports the severity, live-region and fall-through evidence too", async () => {
    const stories = await import("@/components/patterns/StatusBanner.stories");
    for (const name of [
      "Severities",
      "ForcedColours",
      "Dark",
      "LiveRegions",
      "AllFailures",
      "OverriddenMark",
      "UpstreamDown",
      "MappedErrorTypes",
      "UnmappedErrorType",
      "ErrorTypeNotReported",
    ]) {
      expect(Object.keys(stories), name).toContain(name);
    }
  });
});

// ---------------------------------------------------------------------------
// The fall-through, rendered (criterion 6's visible half).
// ---------------------------------------------------------------------------

describe("an unmapped error_type is visible on screen, not only in a type", () => {
  it("renders the generic sentence and the raw error text together", () => {
    const described = describeErrorType(
      "SomeFutureExceptionName",
      "SomeFutureExceptionName: buffer was empty",
    );
    render(
      <StatusBanner
        severity="critical"
        sentence={described.sentence}
        recovery={described.recovery}
        evidence={rawErrorEvidence(described.errorType, described.rawError)}
      />,
    );
    expect(screen.getByText("The run failed.")).toBeInTheDocument();
    expect(screen.getByText("SomeFutureExceptionName")).toBeInTheDocument();
    expect(
      screen.getByText("SomeFutureExceptionName: buffer was empty"),
    ).toBeInTheDocument();
  });

  it("marks an absent raw value rather than dropping the row", () => {
    render(
      <StatusBanner
        severity="critical"
        sentence={describeErrorType(null, null).sentence}
        evidence={rawErrorEvidence(null, null)}
      />,
    );
    const rows = screen.getAllByText("not reported");
    expect(rows).toHaveLength(2);
    for (const row of rows) expect(row).toHaveAttribute("data-present", "false");
  });
});
