"use client";

/**
 * `/` — the landing composer (WO-20; 03 §2.1, §2.2 row 1).
 *
 * THE HAND-OFF IS UNCHANGED, AND THAT IS THE POINT (criterion 2, MUST-KEEP 1).
 * `POST /conversations` → `POST /research` → `router.push('/c/{id}?job={job_id}')`,
 * both ids percent-encoded, in that order. The three lines that did it by hand
 * at `web/app/page.tsx:33-40` are now `LandingComposer`'s, verbatim in
 * behaviour: `web/tests/features/LandingComposer.test.tsx` mirrors
 * `web/tests/HomePage.test.tsx` assertion for assertion, and this route's own
 * test drives the composed page over a mocked `fetch` so the ordering is
 * asserted where it actually happens.
 *
 * WHY THE MACHINE IS MOUNTED HERE. `useJobRun().submit` is the only permitted
 * path to `POST /research` (R-01, H6): the endpoint has no idempotency key
 * (`routes.py:179-197`), so a duplicate is a second charge, and the machine's
 * submission token is what makes a late or duplicated response unable to adopt
 * a run nobody asked for twice. `autoAttach` is left on and `jobId` is null,
 * so this provider never attaches to anything — it exists to own the one
 * submission this page can make.
 *
 * WHAT IS DELIBERATELY NOT WIRED, AND WHY IT IS A BYTE QUESTION. Two of
 * `LandingComposer`'s injection points stay at their defaults:
 *
 *   - `createThread` remains the plain `createConversation`, not
 *     `useCreateConversation().mutateAsync`. The mutation needs a QueryClient
 *     above this page, and TanStack Query in the `(workspace)` layout is
 *     charged to BOTH routes' first-load JavaScript (+8,016 B gzip on `/` when
 *     WO-08 measured it). The rail already keeps its own client in a lazy
 *     chunk for exactly that reason; `/c/[id]` mounts one for the thread read.
 *   - `unreachable` (03 §2.2 row 4) is not passed, because the fact belongs to
 *     the rail's `GET /conversations` and reaching it from here needs the same
 *     shared client. The rail still renders row 4's own alert; what is missing
 *     is the composer's matching refusal, and buying it costs the route more
 *     than the ceiling has.
 *
 * Both are recorded in the PR body rather than smoothed over.
 */

import { LandingComposer } from "@/components/features/LandingComposer";
import { LearnLandingEntry } from "@/components/features/LearnLandingEntry";
import { JobRunProvider } from "@/lib/job/provider";

export default function HomePage() {
  return (
    <JobRunProvider>
      {/*
        The composer is the first thing in `<main>` and its `h1` is the first
        thing in the composer, which is WO-13 criterion 3 — the baseline's
        heading did not start until roughly 440px down a 1200px viewport.
        `overflow-y: auto` because `.ew-shell__surface` is a fixed-height box:
        an over-length question grows the field and the column scrolls rather
        than the page panning (04 §8.3).
      */}
      <div className="mx-auto flex h-full w-full max-w-3xl flex-col justify-center gap-6 overflow-y-auto px-6 py-8">
        <LandingComposer />
        <LearnLandingEntry />
      </div>
    </JobRunProvider>
  );
}
