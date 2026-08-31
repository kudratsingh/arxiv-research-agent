# Learning content

Learning paths, shipped as files in the repository. Phase W has no
content database — `planning/07-learning-platform/02-CONTENT.md` §1.2
designs a Postgres content graph and it arrives in Phase L1 — so the
whole catalogue is a directory of JSON and markdown that lands in the
image beside `src/`.

That is a deliberate trade, not a shortcut. It means every editorial
decision is a line in a diff, every review is a commit, and the licensing
posture is enforced by a schema at load time instead of by a policy
document nobody re-reads.

```
content/
└── paths/
    ├── reading-first-papers/     the flagship path — see below
    │   ├── path.json             the manifest
    │   ├── REVIEW-QUEUE.md       generated; the owner's work list
    │   └── briefings/
    │       └── TEMPLATE.md       the briefing-companion format
    └── fixture-guided-read/      demo scaffolding, labeled as such
        ├── path.json
        └── briefings/*.md
```

## What ships today

| Path | Status | What is in it |
|---|---|---|
| `reading-first-papers` | `proposed` | 10 curated papers + 4 link-out companions, every entry with a one-line rationale. **Publishes nothing yet** — its briefing companions have not been generated, and W-OD-2 has not been granted. |
| `fixture-guided-read` | `published` | Three entries with authored placeholder briefings, so the local demo and the `(learn)` surfaces have a real path shape to render. Every response carries a banner saying exactly that. |

`GET /learn/paths` therefore returns one path — the fixture one — and
that is the honest answer while no reviewed briefing exists.

## The rules, and where they live

`src/content/schema.py` refuses to load a manifest that breaks any of
these. They are validators, not prose, because W-OD-3's posture has to
survive people editing JSON.

| Rule | What it refuses |
|---|---|
| `L1_ARXIV_ABS_ONLY` | A paper linked anywhere but its arXiv **abs** page |
| `L2_NO_FILE_URLS` | Any URL pointing at a file (`.pdf`, `/pdf/`, `/e-print/`, `/ftp/`) |
| `L3_NO_REHOSTING_FIELDS` | A *field* that could hold full text, a PDF, or a transcript |
| `L4_ABSTRACT_ATTRIBUTED` | An abstract with no source and no link to its own abs page |
| `L5_S2_LINKS_BACK` | A citation-ancestry claim with no Semantic Scholar link-back |
| `L6_ID_MATCHES_URL` | A `resource_id` that disagrees with the link it describes |
| `L7_NO_YOUTUBE` | Any YouTube URL or the `video` resource kind |
| `L8_NONCOMMERCIAL` | A missing posture block, or an NC/SA link-out with no licence URL |
| `L9_QUOTES_ATTRIBUTED` | A briefing that block-quotes without attribution, or quotes too much |
| `S1_REVIEW_REQUIRED` | `approved` or above with no named reviewer and date |
| `S2_BRIEFING_REQUIRED` | An approved paper whose briefing is missing, unparseable, or names a different reviewer |
| `S3_PATH_PUBLISH_GATE` | A published path holding an entry still working through the queue |
| `S4_POSITIONS_CONTIGUOUS` | Gaps or duplicates in the reading order |
| `S5_UNIQUE_RESOURCE_IDS` | The same resource twice on one path |
| `S6_GENERATED_NEEDS_RUN` | A `generated` briefing that does not name the run that produced it |
| `S7_FIXTURE_BANNER` | Fixture content without its banner, or real content wearing one |
| `S8_RATIONALE_PRESENT` | An entry with no one-line reason for being there |

**`L7` removes a resource kind that `02` §1.1 defines**, and the reason
matters. YouTube's Developer Policies cap non-authorized metadata
storage at 30 days, refreshed or deleted. A git-tracked manifest cannot
expire — the commit is permanent — and Phase W ships no refresh job. So a
curated video may not be committed here *at all*, and the `video` kind
returns when the weekly `videos.list` refresh that makes it lawful does.

## The status queue

```
proposed ──approve──▶ approved ──publish──▶ published ──link rot──▶ stale
    │
    └────reject────▶ rejected  (kept, with its reason)
```

Only a human moves anything past `proposed` (`02` §3.1), and the schema
makes that structural rather than procedural: `approved` and above
require a named reviewer, a review date, and — for a paper — a briefing
file that exists and names the same reviewer. `stale` and `rejected` both
rank *below* `approved` for serving, so neither can reach a client.

## Working on content

```bash
# Validate everything and regenerate the owner's review queue.
.venv/bin/python -m src.content.review_queue --write

# Fail if a committed REVIEW-QUEUE.md has drifted from its manifest.
.venv/bin/python -m src.content.review_queue --check

# Check every link a manifest publishes. Exit 1 on any broken link.
.venv/bin/python -m src.content.linkcheck
.venv/bin/python -m src.content.linkcheck --json > linkcheck.json

# Serve it locally. The compose demo turns the flag on already.
ENABLE_LEARN_CONTENT=true .venv/bin/python -m src.api.serve
curl -s localhost:8000/learn/paths | jq
```

`ENABLE_LEARN_CONTENT` is off by default in `src/config.py`, on in the
base `docker-compose.yml` (the zero-config demo, where the only
publishable path is the labeled fixture one), and off again in
`deploy/hetzner/compose.prod.yml`.

## Approving an entry

1. Work through `REVIEW-QUEUE.md` — it lists what to check and, more
   usefully, what the validator already checked so you do not spend the
   hours twice.
2. In `path.json`, set the entry's `status` to `approved` and fill in
   `reviewed_by` and `reviewed_at`. To reject it instead, set `status` to
   `rejected` and write `rejection_reason`: `02` §3.1 keeps rejects and
   their reasons as a calibration set, so a rejection is an edit, never a
   deletion.
3. For a paper, make the same edit in the briefing file's provenance
   header. The loader refuses to start if the two disagree, in either
   direction — a manifest that claims a review the file does not, or a
   file that claims one the manifest does not.
4. Regenerate the queue and run the tests:
   `.venv/bin/python -m src.content.review_queue --write && pytest tests/test_content_manifest.py`

## The briefing campaign

`reading-first-papers` names a briefing file for each of its ten papers
and none of them exists yet. That is the pre-campaign state, and it is
recorded in the manifest's own `generation` block: the pipeline, the
exact command, the ceiling, and the decision it waits on
(**W-OD-2** — not granted). No briefing in this directory was produced by
a paid model call, and `tests/test_content_manifest.py` asserts it.
