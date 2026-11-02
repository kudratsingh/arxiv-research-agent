# Proposal: Build a personal daily research workspace

- **Status**: proposed implementation ADR for the owner-adopted direction; number allocation must be reconciled before merge
- **Date**: 2026-11-02
- **Deciders**: Kudrat Singh (product direction); implementation agent (reversible preview choices)

## Context

The September coordination board reserved 0103 for LE-E and 0104 for a verifier
follow-up. The daily workspace proposal is deliberately unnumbered until the
coordinator allocates a free number. No reservation is consumed or overwritten;
the numeric index remains dense through 0102. Assign and index a number before merge. The owner has explicitly moved the personal workflow ahead of
the old evaluation-first sequence; its required evaluation fixes remain W7.

The owner selected daily briefings and guided deep dives, local operation, and
separate approval for paid services. The direction kit in
`planning/11-daily-research-workspace/` replaces Phase-W-first sequencing.
The existing query workbench, guided reading and evaluation evidence remain
available. The reviewed base is `88d283d`; the shared checkout and incoming
kit are preserved while implementation runs in an isolated worktree.

## Decision

The first slice is an explicitly fictional, disconnected preview at `/today`,
`/interests`, `/library`, and `/library/items/[id]`. A separate route group
owns its shell; `/` remains the existing research-a-question workflow. Enable
preview routes explicitly with `WORKSPACE_PREVIEW=1`; run the preview server
on loopback. These routes create no jobs, call no providers and fetch no feeds.
They show source failures, material scope and disabled generation truthfully.

Use the existing fonts, tokens, theme control, focus primitives and responsive
conventions. The signature interaction is a question thread connecting the
source, the owner's saved question and an explicitly proposed next action.
All 384 supplied topic entries remain selectable, with no connected-source
claim. Research navigation is limited to implemented destinations.

For W1 only, a versioned, bounded browser record holds preview interests,
saves, notes, questions and reading anchors. This deliberately extends RC-05:
the two existing cosmetic preferences remain unchanged; one additional key,
`arxiv-agent.workspace-preview.v1`, contains disposable preview data. Its UI
states the storage location, offers export, and reports write failure without
claiming a save. It is never attached to API jobs or sent to a provider.
It is not the durable private workspace: W2 replaces this boundary with
principal-scoped Postgres repositories and an explicit migration/import path.

The personal-local runtime will use a named local operator through the existing
server-only API-key proxy and loopback-only Compose ports. It will preserve
separate auth-off demos and pilot modes. No new API or paid job contract is
claimed shipped by W1. W2 introduces versioned interests/item/reading records;
W3 introduces bounded intake tasks; W7-W9 introduce evidence-scoped generation
admission, separate from metadata collection. Course publication, educational
pilots and the historical five-arm experiment do not block W1-W6.

## Alternatives considered

- Replace the root workbench immediately: rejected until the owner reviews the
  connected preview and existing route contracts can be migrated deliberately.
- Build every backend object before an experience review: delays feedback and
  overcommits to untested navigation. Implement the narrow persistence boundary next.
- Treat fixture generation as funded-agent evidence: invalid. Generated analysis
  needs retained-source, calibration, settings and approved-budget gates.

## Consequences

The owner can review a complete daily loop before funding or enabling sources.
Preview notes are browser-local, not backed up, and must not be confused with
server retention or multi-device identity. Dependency findings must be fixed
before running the preview; no audit thresholds or exceptions are relaxed.
The full destination remains a real metadata workspace followed by approved
grounded briefings and deep dives, documented in the direction kit's status.

## W1 measurement disposition

The preview shell's client entry lives in `(daily)/template.tsx`, behind the
server layout's opt-in check. This keeps the measured client boundary on its
own route segment. Saved preview state is outside the template, so remounts
do not erase continuity. The first draft's separate client shell boundary was
conservatively attributed to legacy routes by the existing budget reader;
its script set was checked against served HTML before selecting the template.
The measurement script and all existing JavaScript ceilings are unchanged.

The four new routes measure 152,994–156,705 B gzip with a 163,840 B ceiling.
All emitted CSS grows from the patched baseline's 11,518 B to 15,016 B for
responsive briefing, reader, interests and mobile panes. The CSS ceiling moves
from 12,288 B to 15,872 B; its derived aggregate follows by the same delta.
The ratchet record carries these measurements and the rejected layout. New
route-specific announcements have one dedicated owner; they never mount the
workbench TraceSpine, preserving one live result announcement per daily route.

## Dependency instrument update

W0 patches Next.js/config to 16.4.4, Storybook to 10.6.5 and Zod to 4.6.6.
Explicit dev-only overrides select Lighthouse 13.6.0, tmp 0.2.7 and basic-ftp
6.2.5. A disposable installation and one local `lhci collect` establish CLI
compatibility before adoption. This changes the Lighthouse instrument from
12.6.1; future comparisons must use the recorded version. No performance or
audit threshold changes. All seven obsolete high-advisory exceptions are
removed; production and full-tree high/critical audits are green. Moderate
findings remain visible. The old nightly matrix has not been re-observed by
this one preview collection.
