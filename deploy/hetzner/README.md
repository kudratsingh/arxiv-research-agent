# Hetzner single-VPS deployment

This is the production path selected for the first deployment (ADR
[0054](../../docs/decisions/0054-hetzner-production-boundary.md)). It
runs Caddy, Next.js, FastAPI, Redis, and Postgres on one Hetzner Cloud
server with Docker Compose.

```text
Internet -> Caddy :443 -> Next.js :3000 -> FastAPI :8000
                                      |-> Redis :6379
                                      `-> Postgres :5432
```

Only Caddy publishes a production host port. Caddy terminates HTTPS and
requires a human login; Next.js injects the separate API key on its
server-only hop to FastAPI. Redis, Postgres, Next.js, and FastAPI stay
on the private Compose network.

## Sizing decision

The initial recommendation is **CAX21 in FSN1** (NBG1 is an equivalent
fallback): 4 shared Arm vCPUs, 8 GB RAM, and 80 GB NVMe. The application
image has already been exercised on Linux/arm64, including an offline
MiniLM encode. Eight GB leaves usable headroom for the 1.7 GB API image,
model inference, the Next.js server, Redis, Postgres, and image builds.

As of 2026-08-27, Hetzner lists CAX21 at $12.49/month before tax and
before the optional $0.60/month Primary IPv4, with hourly billing capped
at the monthly price. Confirm the current Console total before creating
the server: [current Cloud prices](https://www.hetzner.com/cloud/) and
[Primary IP pricing](https://docs.hetzner.com/cloud/servers/primary-ips/overview/).

The CAX line uses shared CPU. If measurements show sustained CPU
contention, resize after collecting evidence; a dedicated CCX instance
is the predictable-performance option, but costs materially more. Do
not enable Hetzner Backups, Volumes, Load Balancers, or other paid
options without explicit approval.

## Before provisioning

Have these ready:

- A Hetzner Cloud project and an SSH public key.
- A domain or subdomain whose DNS you can edit.
- The current administrator public IP, so SSH can be allowlisted.
- An Anthropic key with an account/project spend limit.
- Approval for the exact server, IPv4, tax, and any backup charge shown
  in the Hetzner Console.

Creating the server or enabling Backups starts billable resources. Stop
for approval before either action.

## Provisioning contract

Create Ubuntu 24.04 LTS on the selected CAX21 with the SSH key. Attach a
Hetzner Cloud Firewall before exposing the host:

| Direction | Protocol | Port | Source |
|---|---|---:|---|
| inbound | TCP | 22 | administrator IP `/32` only |
| inbound | TCP | 80 | any IPv4/IPv6 |
| inbound | TCP | 443 | any IPv4/IPv6 |
| outbound | any | any | any |

Hetzner Cloud Firewalls are stateful and apply an implicit deny to
unmatched inbound traffic. Docker's documentation warns that published
container ports can bypass `ufw`; the production Compose file therefore
publishes only Caddy's 80/443, while the Cloud Firewall is the outer
control.

Point the chosen hostname's A record at the Primary IPv4 and its AAAA
record at the assigned IPv6. Caddy cannot obtain a public certificate
until the hostname resolves to the server and inbound 80/443 work.

## Host setup

Install Docker Engine and the Compose plugin from Docker's official apt
repository, not Ubuntu's `docker.io` package. Follow the current
[Docker Ubuntu installation instructions](https://docs.docker.com/engine/install/ubuntu/)
for Ubuntu 24.04, then verify:

```bash
docker version
docker compose version
```

Clone the public repository and pin the exact reviewed commit. Replace
`<release-commit>` only with a commit that is on `main` and has green CI.

```bash
git clone https://github.com/kudratsingh/arxiv-research-agent.git
cd arxiv-research-agent
git checkout --detach <release-commit>
cp deploy/hetzner/env.example .env
```

Fill `.env` on the server. Generate the two machine secrets separately:

```bash
openssl rand -hex 32
openssl rand -hex 32
```

Use one for `WEB_API_KEY` and the other for `POSTGRES_PASSWORD`. Generate
the Caddy login hash interactively so the plaintext is not written into
shell history:

```bash
docker run --rm -it caddy:2.11.4-alpine caddy hash-password
```

Put the result in `APP_PASSWORD_HASH` inside **single quotes**. Caddy
stores only the bcrypt hash; `.env` is ignored by Git.

## Validate and start

The first build downloads dependencies and the MiniLM model but makes no
Anthropic request. Validate interpolation before building:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/hetzner/compose.prod.yml \
  config --quiet
```

Then build and start from the pinned commit:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/hetzner/compose.prod.yml \
  up --build -d
```

Inspect the state without printing the environment:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/hetzner/compose.prod.yml \
  ps
docker compose \
  -f docker-compose.yml \
  -f deploy/hetzner/compose.prod.yml \
  logs --tail=100 app web caddy
```

Expected: all five services become healthy. An unauthenticated request
to `https://<APP_DOMAIN>/` returns 401 from Caddy. Entering the Caddy
credentials in a browser loads the UI. From the server, FastAPI's
dependency detail is available without exposing its port:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/hetzner/compose.prod.yml \
  exec app curl -fsS http://localhost:8000/healthz
```

The final browser research query is a paid Anthropic end-to-end test.
Confirm the provider budget and get explicit approval before submitting
it; start with one narrow query and keep the configured `MAX_COST_USD`
ceiling.

## Update and rollback

Deploy only a reviewed `main` commit. Before an update, record the
currently checked-out SHA (`git rev-parse HEAD`), fetch, detach at the
new SHA, rebuild, and wait for health. The named volumes survive
rebuilds and ordinary `down`/`up` cycles.

Rollback is the same operation with the previously recorded SHA:

```bash
git checkout --detach <previous-release-commit>
docker compose \
  -f docker-compose.yml \
  -f deploy/hetzner/compose.prod.yml \
  up --build -d
```

Never use `docker compose down -v` in production: it deletes the Redis,
Postgres, and Caddy volumes.

## Data protection

Named volumes provide persistence across container replacement; they
are not an independent backup. Before migrations or upgrades, make a
logical Postgres dump and copy it off the VPS. Hetzner's optional Cloud
Backups are daily with the latest seven retained, but they are a paid
option and Hetzner still recommends an independent backup. Enabling
them requires separate cost approval.

Redis contains job/event state; Postgres contains conversations,
checkpoints, paper text, and embedding caches. Caddy's `/data` volume
contains certificate state. Document and test restoration before
treating any backup path as complete.
