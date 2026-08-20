# 0045. Supply-chain hardening: version ranges + lockfile, lazy API package, web stack renewal, license posture

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: kudratsingh

## Context

An external audit surfaced a cluster of supply-chain findings that
share one root cause: the repo pinned nothing and recorded nothing.

**No Python lockfile, unbounded floors.** Every runtime dependency
floated on a bare `>=`, so each Docker build and CI job re-resolved
fresh from PyPI — the tested set and the shipped set were not
identical by construction, a released tag could not be rebuilt to the
same dependency graph, and an unpinned ruff/mypy minor could fail CI
on unchanged `main` with no commit to revert. Worse, several declared
floors were *uninstallable on the project's own Python* (3.14, pinned
in `.python-version`): PyMuPDF 1.24.0, faiss-cpu 1.8.0 and
psycopg-binary 3.2.0 ship no cp314 wheel (first cp314 releases:
1.27.2, 1.12.0 and 3.2.10 respectively — verified against PyPI), and
the `langgraph>=0.2.0` floor advertised a pre-1.x API the code cannot
run on.

**Dead web runtime lines.** The demo UI (ADR 0029) pinned `next` to
`^14.2.15` — the whole 14.x line is EOL, and its reachable
RSC-deserialization advisories have no fix inside `^14`. All three
`web/Dockerfile` stages and CI ran Node 20, EOL since 2026-04-30: a
runtime CVE could not be remediated by rebuilding because no patched
`node:20-alpine` will ever be published.

**Eager ML-stack import.** `src/api/__init__.py` eagerly re-exported
`create_app`, so importing *any* `src.api.*` module — including the
DDL-only `admin_migrate` CLI — transitively loaded
torch/faiss/sentence-transformers/PyMuPDF/reportlab. Measured with
`python -X importtime -c "import src.api.schemas"`: **5,200,966 µs
cumulative (3.52 s wall)** before, **87,253 µs (0.06 s wall)** after,
with none of the five heavy distributions loaded.

**Unpackaged install.** Setuptools flat-layout auto-discovery
installed the *contents* of `src/` as ~11 generically-named top-level
modules (`api`, `config`, `main`, …) in site-packages — colliding
with any same-named dependency file and matching no import in the
codebase (everything imports `src.*`).

**Unrecorded AGPL exposure.** PyMuPDF is AGPL-3.0-or-commercial and
sits on the core PDF path, but the repo declared no license posture
at all.

## Decision

### 1. Two-file dependency contract: ranges + lock

`pyproject.toml` stays authoritative for **ranges**; a committed
`requirements-lock.txt` (a `pip freeze` of the tested venv, Python
3.14) is authoritative for **the tested set**. Range policy:

- **Floor** = the oldest release that (a) ships a wheel for the
  pinned Python and (b) speaks the API the code targets. That raises
  `PyMuPDF>=1.27.2`, `faiss-cpu>=1.12.0`, `psycopg>=3.2.10`,
  `langgraph>=1.0.0` / `langchain-core>=1.0.0` (the code targets the
  1.x API), and `langgraph-checkpoint-{sqlite,postgres}>=3.1.0` (the
  3.x line is the one compatible with langgraph 1.x).
- **Cap** = `< next major` above the locked version, so an upstream
  major cannot land untested through a fresh resolve.
- **mypy and ruff are exact-pinned** in the dev extra — a floating
  minor of either is a CI gate that moves on its own.

CI's typecheck and tests jobs install `-r requirements-lock.txt`,
then the package itself with `--no-deps`, then run `pip check` so
lock/range drift fails the job instead of hiding. The lint job greps
its exact ruff pin out of the lock. The update procedure lives in
`docs/development.md` ("Dependency locking").

Known limits, accepted deliberately: the lock is frozen on one
platform (platform-only transitive wheels, e.g. torch's `nvidia-*`
on Linux, resolve at install time) and carries no `--require-hashes`.
A hashed cross-platform lock (`uv lock` / `pip-compile
--generate-hashes`) is the recorded follow-up — it needs a resolver
tool this repo does not vendor yet.

Advisory note: locked `langgraph-checkpoint-{sqlite,postgres}==3.1.0`
carry a namespace-scoping advisory in their *Store* implementations,
which this codebase does not invoke (it uses only the checkpointers —
the audit confirmed non-reachability). First patched release is
3.1.1; the next lock refresh picks it up.

### 2. Explicit packaging

`[tool.setuptools.packages.find] include = ["src*"], namespaces =
false` — the distribution installs as a single top-level `src`
package matching every import in the codebase, instead of scattering
generic module names across the site-packages root.

### 3. Lazy `src.api` package (PEP 562)

The package `__init__` resolves its four public names (`create_app`,
`Job`, `JobStatus`, `JobStore`) through a module `__getattr__`, with
a `TYPE_CHECKING` block so mypy/IDEs see the same surface. The
documented entry point `from src.api import create_app` is unchanged;
`import src.api.<light submodule>` no longer builds the ML graph
(numbers above). A subprocess-based test pins the contract.

### 4. Web stack: Next 15.5 + React 19, Node 22, vitest 4

- `next ^15.5.23` (the maintained backport line) + `react`/`react-dom`
  19, `eslint-config-next` 15.5, `@types/react{,-dom}` 19. The app is
  fully client-rendered (`"use client"` throughout, `useParams` only),
  so Next 15's async-request-API breaking changes have zero surface
  here. Proven in-tree: `npm install`, `tsc --noEmit`, `next lint`,
  vitest (56/56) and `next build` all pass.
- **Why not Next 16 (latest)**: 16 removes `next lint`, which the lint
  script and CI use — the migration to the ESLint CLI (and eslint 9
  flat config; eslint 8 is EOL too) is real churn that belongs in its
  own PR. Residual exposure accepted until then: `npm audit` reports 3
  high advisories pinned inside Next 15's own dependency tree
  (bundled postcss 8.4.31, sharp < 0.35) that only a Next 16 bump
  clears. None are in the demo UI's request path (no `next/image`, no
  server-side CSS processing of untrusted input).
- vitest 2 → 4 (+ `@vitejs/plugin-react` 6, vite 8, jsdom 30) clears
  the dev-only *critical* (vitest UI arbitrary file read/execute) and
  the vite/esbuild dev-server advisories.
- All three `web/Dockerfile` stages and CI's `setup-node` move to
  Node 22 (current LTS, maintained to 2027-04-30).

### 5. Docker image hygiene

The builder stage stops installing `curl` it never used; every
compiled dependency ships a cp314 wheel, guaranteed by the new
floors. Base images (`python:3.14-slim`, `node:22-alpine`) are
current; digest-pinning them is deferred until a bot (Dependabot /
Renovate) exists to maintain digests — a stale hand-pinned digest is
worse than a floating tag.

### 6. License posture: recorded, not chosen

PyMuPDF is AGPL-3.0 dual-licensed and this service is network-served,
which is precisely the case AGPL §13 attaches a source-offer
obligation to. This ADR records the exposure and the three exits
(adopt AGPL with a LICENSE + §13 offer; buy the Artifex commercial
license; swap to a permissive extractor — `pypdfium2` Apache-2.0 —
behind the existing `src/tools/pdf_parser.py` boundary). **Choosing
the project's license is the owner's decision and is deliberately not
made here**; no LICENSE file or `license` field is added until it is.
`docs/development.md` carries the contributor-facing note.

## Alternatives considered

- **uv / pip-compile hashed lock now** — the right end state, but
  neither tool is in the shared venv and this change refuses to add
  tooling as a side effect; the freeze-based lock captures 90% of the
  value (identical tested/gated sets) today. Follow-up.
- **Loose floors, no caps ("let pip pick")** — status quo; rejected,
  it is how the uninstallable-floor and untested-major failure modes
  arose.
- **Exact-pin everything in pyproject** — collapses ranges into a
  second lockfile and makes every dependency bump a metadata edit;
  ranges + lock keeps intent and reality separate.
- **Next 16.3.1** — see §4; deferred, not rejected.
- **Pin Next at 14.2.35 (latest 14.x)** — leaves unfixable advisories
  in place on an EOL line; only defensible if the 15 upgrade had
  failed, and it passed everything.
- **Keep eager `src/api/__init__.py` re-exports** — simpler file, but
  a 3.5 s / ~550 MB tax on every `src.api.*` import including CLIs
  that never touch the ML stack.

## Consequences

- **Positive**: reproducible CI and rebuildable releases; floors that
  are actually installable on the pinned Python; the gate tools can't
  drift; supported web runtime lines with the advisory residue named
  and bounded; `src.api` imports proportional to what's used; the
  AGPL exposure is on the record instead of latent.
- **Negative**: dependency bumps now require the two-file dance in
  `docs/development.md`; caps mean new majors need a deliberate PR;
  the lock is single-platform and unhashed until the uv/pip-compile
  follow-up; 3 high npm advisories remain inside Next 15's tree until
  the Next 16 PR.
- **Follow-ups**: hashed cross-platform lock; Next 16 + ESLint CLI +
  eslint 9 migration; Dependabot/Renovate config + `pip-audit` /
  `npm audit` CI steps (owner: CI lane); lock refresh to pick up
  `langgraph-checkpoint-* 3.1.1`; the license decision itself.
