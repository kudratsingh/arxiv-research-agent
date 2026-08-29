"use client";

/**
 * LandingComposer — `QueryComposer` wired to the job machine (WO-13).
 *
 * IT IS NOT MOUNTED ON `/` YET, AND THE REASON IS MEASURED. Wiring it into
 * `web/app/(workspace)/page.tsx` puts the composer, the primitives it uses
 * and the whole of `lib/job/` into the landing route's first-load
 * JavaScript: **154,202 B against 04 §8.1's 148,480 B ceiling, a 5,722 B
 * breach**, measured on this tree. The composer stack is +10,333 B gzip and
 * `/` has 4,611 B of headroom now that WO-08's shell is on the route.
 *
 * There is no reduction that closes that gap honestly. `useJobRun().submit`
 * is the only permitted submission path (R-01), so `lib/job/` cannot leave;
 * lazy-loading `StatusBanner` recovers ~1 KB of it. So the mount belongs to
 * WO-20 (route composition — its criterion 2 is this exact hand-off), where
 * it can be weighed against the rest of the route's payload and, if it
 * still does not fit, against `budgets.json`'s ratchet rule with a stated
 * reason. Shipping the component without mounting it costs the route
 * nothing: `npm run budgets` on this branch is byte-identical to main.
 *
 * The whole path is proven at the component level in
 * `web/tests/features/LandingComposer.test.tsx`, which mirrors
 * `web/tests/HomePage.test.tsx` assertion for assertion.
 *
 * WHY THIS IS A SECOND FILE. `QueryComposer.tsx` holds no data and makes
 * no request, which is what lets its ten stories render with no provider
 * and keeps `lib/job/` out of the Storybook project's module graph — the
 * merged-coverage hazard `vitest.config.mts` records for WO-13 … WO-19.
 * Everything that needs the network lives here, and nothing imports this
 * file from a story.
 *
 * THE SUBMISSION PATH, AND THE ONE RULE IT OBEYS. `useJobRun().submit()`
 * is the only way this surface reaches `POST /research` — never
 * `api.submitResearch` directly, never a TanStack mutation. That is R-01
 * and H6: the endpoint has no idempotency key (`routes.py:179-197`), a
 * duplicate is a second charge, and Query's default `networkMode:
 * "online"` would *pause a mutation while offline and resume it on
 * reconnect*, which is an automatic replay of a paid run. The machine's
 * submission token (`lib/job/types.ts`, `Submission.token`) is what makes
 * a late or duplicated response unable to adopt a job nobody asked for
 * twice.
 *
 * The plan-review bypass field (03 §8.4, H12) is never passed, and cannot
 * be from here: `submit()` takes a query and a thread id and nothing else.
 * Its name is deliberately not spelled anywhere outside `lib/api` —
 * `web/tests/api.test.ts` walks `app/`, `components/`, `lib/` and `tests/`
 * and fails on the literal, so containment is a property of the tree
 * rather than of this comment.
 *
 * THE HAND-OFF IS MUST-KEEP #1 AND IS UNCHANGED. `POST /conversations` →
 * `POST /research` → `router.push('/c/{id}?job={job_id}')`, both ids
 * percent-encoded, exactly as `web/app/page.tsx:33-40` does it today. The
 * push is driven from the machine's `jobId` rather than from `submit()`'s
 * return, so the URL can only ever carry a job the machine actually
 * adopted.
 *
 * H7 — THE ORPHAN THREAD. The thread is created *before* the run is
 * submitted, and both writes spend rate-limit budget (`routes.py:545`,
 * `:157`), so a submission that fails at the second write has already left
 * a real, empty thread behind. When that happens the composer says so and
 * offers it, rather than leaving it to be discovered in the rail.
 *
 * TWO INJECTION POINTS, BOTH FOR THE WORK ORDERS DOWNSTREAM:
 *
 *   - `createThread` defaults to `createConversation` from `lib/api` — a
 *     plain call, not `useCreateConversation()`. On `/` that is not a
 *     preference: mounting `QueryProvider` to reach the mutation would put
 *     TanStack Query (~13 KB gzip, `app/providers.tsx`) into the landing
 *     route's first-load JS, and 04 §8.1's `/` row has under 9 KB of
 *     headroom. WO-20 composes this on the workspace segment, where the
 *     provider is mounted for the rail anyway; there it should pass
 *     `useCreateConversation().mutateAsync` so the new thread seeds the
 *     list cache. The signature is deliberately the mutation's.
 *   - `unreachable` is 03 §2.2 row 4 — the composer refuses while the
 *     research service is known to be down. The knowledge comes from the
 *     rail's `GET /conversations` (WO-14), so it arrives as a prop rather
 *     than being re-fetched here; a composer that issued its own health
 *     read would be a second source of truth for the same fact.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { QueryComposer } from "@/components/features/QueryComposer";
import { ApiError, createConversation } from "@/lib/api";
import type { ApiFailure, ConversationDetail } from "@/lib/api";
import { useJobRun } from "@/lib/job/provider";

/** The href the accepted run is handed off to (MUST-KEEP #1). */
export function handoffHref(conversationId: string, jobId: string): string {
  return `/c/${encodeURIComponent(conversationId)}?job=${encodeURIComponent(jobId)}`;
}

/** The href of a thread with nothing running in it (H7's offer). */
export function threadHref(conversationId: string): string {
  return `/c/${encodeURIComponent(conversationId)}`;
}

/**
 * Anything thrown by a write, as an `ApiFailure`.
 *
 * `ApiError` always carries one (`lib/api/errors.ts`); a non-`ApiError`
 * throw is a bug in this bundle rather than an answer from the server, and
 * `unknown` is the union's own word for that.
 */
function asFailure(error: unknown): ApiFailure {
  if (error instanceof ApiError) return error.failure;
  return { kind: "unknown", status: null, message: "", raw: error };
}

/**
 * The fall-back for a rejected submission the machine could not normalize.
 *
 * `submit_rejected` carries `failure: null` when what was thrown was not
 * an `ApiError` — a bug in this bundle rather than an answer from the
 * server. The banner still renders, because a failure with no sentence is
 * indistinguishable on screen from a submission that never happened.
 */
const UNNORMALIZED_SUBMIT_FAILURE: ApiFailure = {
  kind: "unknown",
  status: null,
  message: "",
  raw: null,
};

export interface LandingComposerProps {
  /**
   * Creates the thread the run will belong to. Defaults to a plain
   * `POST /conversations`; see the header for why it is not the mutation.
   */
  createThread?: (title?: string) => Promise<ConversationDetail>;
  /** 03 §2.2 row 4, supplied by whatever already knows (WO-14's rail). */
  unreachable?: ApiFailure | null;
  /** Overrides `router.push`. Present so the hand-off is assertable. */
  onHandoff?: (href: string) => void;
  autoFocus?: boolean;
  className?: string;
}

export function LandingComposer({
  createThread = createConversation,
  unreachable = null,
  onHandoff,
  autoFocus = false,
  className,
}: LandingComposerProps) {
  const router = useRouter();
  const { state, submit } = useJobRun();

  const [question, setQuestion] = useState("");
  /** The thread this attempt created, kept for the hand-off and for H7. */
  const [threadId, setThreadId] = useState<string | null>(null);
  /** `POST /conversations` failed, so no run was ever submitted. */
  const [threadFailure, setThreadFailure] = useState<ApiFailure | null>(null);
  /** True from the first write until the machine settles the attempt. */
  const [creating, setCreating] = useState(false);

  // The second of the three duplicate-submit guards (the composer's ref is
  // the first, the machine's `submitInFlightRef` the third). This one
  // covers the window the other two cannot see: between `POST
  // /conversations` being issued and `POST /research` starting, the
  // machine is still `idle` and would happily accept a submission.
  const busyRef = useRef(false);
  /** So the hand-off fires once per accepted run, never once per render. */
  const handedOffRef = useRef<string | null>(null);
  /**
   * The empty thread a previous attempt already paid for.
   *
   * A manual resubmit after a failed `POST /research` must NOT create a
   * second thread: the first one is real, empty and already in the rail,
   * and a landing submission spends two rate-limit slots against a
   * production ceiling of 20 an hour (`deploy/hetzner/compose.prod.yml:18`,
   * WO-13's risk note). Reusing it costs one slot instead of two and
   * leaves one orphan instead of a trail of them.
   */
  const reusableThreadRef = useRef<string | null>(null);

  const handleSubmit = useCallback(
    async (query: string): Promise<void> => {
      if (busyRef.current) return;
      busyRef.current = true;
      setCreating(true);
      setThreadFailure(null);

      let conversationId = reusableThreadRef.current;
      if (conversationId === null) {
        try {
          const thread = await createThread();
          conversationId = thread.conversation_id;
        } catch (error) {
          // Nothing was submitted, so there is no orphan to offer: the
          // thread is precisely the thing that failed to exist.
          setThreadFailure(asFailure(error));
          setCreating(false);
          busyRef.current = false;
          return;
        }
        reusableThreadRef.current = conversationId;
        setThreadId(conversationId);
      }

      // From here the machine owns the outcome. `submit` resolves once
      // `POST /research` has answered either way; what it answered is read
      // off `state`, which is the single source of truth for the run.
      await submit(query, { conversationId });
      setCreating(false);
      busyRef.current = false;
    },
    [createThread, submit],
  );

  // The hand-off. Driven by the machine's adopted job rather than by
  // `submit()`'s return value, so `?job=` can only ever name a run the
  // machine really attached to (MUST-KEEP #1, ADR 0053).
  const acceptedJobId = state.jobId;
  useEffect(() => {
    if (acceptedJobId === null || threadId === null) return;
    if (handedOffRef.current === acceptedJobId) return;
    handedOffRef.current = acceptedJobId;
    const href = handoffHref(threadId, acceptedJobId);
    if (onHandoff !== undefined) onHandoff(href);
    else router.push(href);
  }, [acceptedJobId, onHandoff, router, threadId]);

  const submitFailed = state.phase === "submit_failed";
  const failure = submitFailed
    ? (state.failure ?? UNNORMALIZED_SUBMIT_FAILURE)
    : threadFailure;

  return (
    <QueryComposer
      variant="landing"
      value={question}
      onValueChange={setQuestion}
      onSubmit={handleSubmit}
      // WO-20 ADDED `acceptedJobId !== null`, AND IT IS AN R-01 FIX RATHER
      // THAN A POLISH. `submit()` resolves the moment `POST /research`
      // answers, so between the hand-off firing and the browser actually
      // leaving `/` the composer was idle again — and a second click in that
      // window reuses the thread and buys a SECOND run. WO-13 could not see
      // it: nothing mounted this component, and its own double-click test
      // covers the in-flight window, which is a different window.
      // `web/tests/HomePage.test.tsx` clicks after the hand-off and counts.
      pending={creating || state.phase === "submitting" || acceptedJobId !== null}
      unreachable={unreachable}
      failure={failure}
      // H7: only a failure that happened AFTER the thread existed can
      // offer it. A thread-creation failure has nothing to offer, and a
      // successful run has navigated away.
      orphanThreadHref={
        submitFailed && threadId !== null ? threadHref(threadId) : null
      }
      autoFocus={autoFocus}
      className={className}
    />
  );
}
