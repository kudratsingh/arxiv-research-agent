# 0054. Close the production boundary for a single Hetzner VPS

- **Status**: accepted
- **Date**: 2026-08-27
- **Deciders**: maintainer

## Context

The four-service Compose demo passed its local production-wiring smoke,
but it was not safe or economical to publish on an internet host.

The image installed the full macOS-generated CI lock. On Linux, its
PyPI Torch wheel brought CUDA packages into a CPU-only service, and the
runtime also shipped pytest, mypy, and ruff. The measured image was
5.88 GB. That is needless disk, pull time, and attack surface on a small
VPS.

API-key auth existed, but the browser UI could not use it: `EventSource`
cannot attach `X-API-Key`, and shipping the key to browser JavaScript
would expose the one credential capable of creating paid work. The
demo therefore stayed auth-off. Next.js 15 also had three high-severity
production dependency findings in `npm audit` by deployment time.

Finally, the base Compose file published FastAPI and Next.js on every
host interface, embedded the development Postgres password, and had no
TLS edge or human-facing access control. A public UI that can initiate
Anthropic calls needs an outer gate even if its internal API hop is
authenticated.

The operator selected a single Hetzner VPS as the first deployment
target. The expected load is one maintainer/demo user, not a high-
availability multi-host service.

## Decision

### Generate a runtime lock and force CPU-only Torch

`requirements-runtime-lock.txt` is a mechanically derived, exact
subset of the full tested lock. `scripts/derive_runtime_lock.py --check`
makes drift fail in the suite. The Docker builder installs the locked
Torch version from PyTorch's official CPU wheel index on both amd64 and
arm64, then installs the runtime subset and the project with `--no-deps`.
The model remains baked into the image.

Linux CI typecheck, pytest, and nightly-eval environments preinstall
that same locked `+cpu` artifact before `requirements-lock.txt`. The
lock's public `torch==X.Y.Z` pin accepts the local-version wheel, so pip
keeps it rather than resolving PyPI's CUDA graph. This makes the runtime
lock check platform-stable and makes the Linux gates exercise the
artifact production actually ships.

The resulting Linux/arm64 image is 1.70 GB and, under `--network none`
with Hugging Face/Transformers offline flags, reports `torch 2.12.1+cpu`
and produces a `(1, 384)` MiniLM vector. pytest and mypy are absent.

### Put API authentication in a server-only same-origin proxy

Upgrade the web app to Next.js 16.3 and ESLint 9. Browser calls now use
same-origin `/api`. A catch-all Node route streams upstream responses
between the browser and the private FastAPI service, injects
`X-API-Key` from `ARXIV_API_KEY`, and forwards only an allowlist of
headers. The key exists only in the web container environment and is
never a build argument or public environment variable.

The proxy streams SSE and export bodies without buffering. It rejects
credentialed/non-HTTP upstream URLs, returns 502 for an unreachable
upstream, and has route-level tests. With same-origin traffic, CORS is
disabled by default.

### Make local exposure explicit and production exposure minimal

Base Compose host ports default to `127.0.0.1`; a developer must opt in
to broader binding. Postgres user/password/database are parameterized.
The Hetzner overlay removes the FastAPI and Next.js published ports
entirely, requires unique web/API and database secrets, forces API auth
and prompt isolation on, and retains the per-run/per-hour spend guards.

Caddy 2.11.4 is the only public service. Its hostname triggers automatic
HTTPS, it reverse-proxies to Next.js on the private Compose network, and
its certificate/config state lives in named volumes. Caddy basic auth
protects the whole UI with a bcrypt hash, limits request bodies to 1 MB,
adds conservative security headers, and emits JSON access logs.

Deploy from an exact reviewed Git commit and build on the VPS for the
first release. This avoids a new registry credential and multi-
architecture publishing workflow before one is operationally needed.
The checkout SHA is the release identifier and rollback target.

Use a Hetzner Cloud Firewall as the outer network control: SSH only
from the administrator IP, HTTP/HTTPS from the internet, implicit deny
for other inbound traffic. Redis and Postgres never publish host ports.

## Alternatives considered

- **Put the API key in `NEXT_PUBLIC_*` and call FastAPI directly** —
  any visitor could extract the credential from JavaScript and spend
  the Anthropic account. `EventSource` still cannot set the header.
- **Leave auth off and rely only on an obscure URL** — no security
  boundary and no protection from automated discovery or abuse.
- **Expose FastAPI and rely on `ufw`** — Docker-published ports can
  bypass host firewall rules. Removing the production port is a
  stronger invariant; Hetzner's stateful Cloud Firewall remains the
  outer control.
- **Managed Postgres/Redis plus a separate frontend host** — stronger
  failure isolation but more paid resources and operational seams than
  this single-user first release needs.
- **Kubernetes** — no multi-host scheduling need; it would add control-
  plane and secret-management complexity without solving a current
  constraint.
- **Publish multi-architecture images to GHCR immediately** — useful
  once deployments are frequent, but it adds package visibility,
  registry authentication, retention, and release workflow decisions.
  Building the pinned source on an 8 GB VPS is slower but simpler and
  independently reproducible for the first deployment.
- **Use Hetzner Cloud Backups as the only backup** — convenient but
  paid, limited to seven daily copies, and not independent. Named
  volumes plus an off-host logical database backup remain necessary.

## Consequences

- **Positive**: the authenticated browser-to-database path works
  without exposing an API secret or a non-TLS application port.
- **Positive**: the CPU-only runtime is about 71% smaller than the
  first measured image and contains no test/type/lint tooling.
- **Positive**: local development stays one Compose command, with
  safer loopback defaults; production differences are reviewable in
  one overlay.
- **Positive**: Caddy owns certificate issuance/renewal and the only
  public sockets; the app does not implement TLS.
- **Negative**: the single VPS is one failure domain. Updates rebuild
  on the host and can be slow; there is no zero-downtime rollout.
- **Negative**: Caddy basic auth is intentionally a one-user gate, not
  product identity or multi-tenant browser authorization.
- **Negative**: named volumes are durable only relative to container
  replacement, not server loss.
- **Follow-ups**: after real resource measurements, decide whether to
  keep CAX21 or resize; add an image publishing workflow if deploy
  frequency warrants it; select and test an independent off-host
  backup; add `/readyz` if a future load balancer needs dependency-
  gated routing.
