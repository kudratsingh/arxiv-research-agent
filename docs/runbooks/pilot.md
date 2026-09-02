# Runbook — the bounded pilot

> ## ⚠ NO PILOT MAY BE INVITED FROM THIS FILE
>
> Owner decision **W-OD-5** is open. It covers the ≤5 invitee names, the
> deployment they use, the pilot inference budget, the at-cap behaviour, and
> whether pilot keys keep `POST /research` rights. Until it is decided and
> recorded, this runbook is a procedure with no authorisation behind it.
>
> The [standing cost lock](../../planning/07-learning-platform/STATUS.md)
> (2026-08-30, reaffirmed) says the same thing in the general form: *no funded
> model run, deployment, public launch, or pilot invitation may occur without
> a fresh explicit owner approval.*
>
> **W-OD-6** (the ≥40% 7-day-return threshold and the 14-day window) must also
> be ratified **before** the first onboarding — the dependency edge WO-W18 →
> WO-W17 exists to enforce that ordering, and
> [`evidence/gate-w2/engagement-threshold.md`](../../planning/07-learning-platform/evidence/gate-w2/engagement-threshold.md)
> is where the ratification is recorded.

The mechanism this runbook operates is [ADR
0063](../decisions/0063-pilot-principal-edge-mapping.md) and
[`deploy/pilot/`](../../deploy/pilot/README.md). Read
[`docs/security.md`](../security.md) §"Pilot principals at the edge" for what
it does and does not defend.

---

## 1. The rule that has no undo

**A pilot key is issued fresh per person and is never reassigned.**

This is scope ruling SR-02, and it exists because of MT-01 finding **F1**:
`principal_key_id` is a *mutable display name*, not a stable owner id. Every
row this product writes about a person — their threads, their guided sessions,
their learner profile, their progress ledger — is keyed on that name (ADR
0036, ADR 0058). So:

- Reusing a retired `key_id` for a new person hands the new person the old
  person's entire learning history, silently, with no error anywhere.
- Renaming a `key_id` orphans everything the old name owned. `_check_ownership`
  makes it invisible rather than wrong, which is safer and still a data loss.

There is no code path that prevents this, and Phase W does not build one — the
real fix is MT-01 / L0-05. What the code *does* enforce is the two adjacent
mistakes: the web tier refuses a map in which two pilots share an `api_key` or
a `key_id`, and `src/api/auth.py::load_keystore_from_file` refuses a keystore
with a duplicate name or a duplicate secret. Neither of them can see that
`pilot-ada` in September is a different human from `pilot-ada` in November.
**That is the human's job, and this section is the whole of the control.**

Practical consequences:

- Name keys so reuse is impossible by construction. `pilot-<given-name>-<YYYY-MM>`
  is the convention this runbook uses: `pilot-ada-2026-09`.
- Never edit a `key_id` in place. Revoke and issue a new one.
- Keep §6's register. It is the only record of which human a `key_id` meant.

---

## 2. Before the first pilot

Ordered, and each step is a gate on the next.

1. **W-OD-6 ratified.** The engagement threshold and the 14-day window, with a
   date that *precedes* every onboarding date. Recorded in
   `evidence/gate-w2/engagement-threshold.md`.
2. **W-OD-5 decided.** Names, deployment, budget, at-cap behaviour, research
   rights. Record the answers in `evidence/gate-w2/pilot-record.md` §Approval
   before touching anything below.
3. **§3's arithmetic re-run with W-OD-5's numbers**, and the result inside the
   approved budget. If it is not, the settings change, not the sentence.
4. **The provider account has a limit.** An Anthropic account budget and
   project limit, set independently of anything in this repository. SR-09's
   arithmetic is a bound on what the *application* will spend; the account
   limit is what holds if the arithmetic is wrong.
5. **The deployment exists and is reachable over HTTPS**, per
   `deploy/hetzner/README.md`'s provisioning contract with
   `deploy/pilot/compose.pilot.yml` in place of the prod overlay.

---

## 3. SR-09 — the worst-case spend arithmetic

MT-01 finding **F4** is real and unfixed in Phase W: *there is no aggregate
spend cap.* The global cap is Phase L0-01. The pilot is acceptable without it
**only** because the exposure is bounded by construction, and SR-09 requires
the bound to be written down. This is where it is written down.

### The formula

```
worst_case_usd  =  N  ×  L  ×  24 × D  ×  C_max

  N      pilots in the cohort                     ≤ 5 (SR-09)
  L      accepted job submissions per principal    api_key_hourly_limit
         per hour                                  (per principal, Redis-backed,
                                                    ADR 0037)
  D      observation window, in days               14 (SR-10)
  C_max  most any one job may spend                max(C_session, C_research)
  C_session   per guided session                   learning_session_max_cost_usd
  C_research  per research run                     max_cost_usd, or 0 if
                                                   W-OD-5 withholds POST /research
```

It is a **conservative** bound in two ways, both deliberate. Learner *turns*
also consume the hourly bucket without creating a job, so the real number of
job-creating submissions is below `L`; and no pilot is awake for 336 hours.
A worst case that assumes a hostile insomniac is the only worst case worth
writing down.

It is **not** a control. Nothing enforces `worst_case_usd`. The enforced
quantities are the per-job ceilings (`call_llm`, ADR 0051/0062) and the
per-principal hourly limit (ADR 0037). This arithmetic is how you decide
whether those two, multiplied out, are a number you are willing to lose.

### The terms, for this pilot

| Term | Value | Source |
|---|---|---|
| `N` | **_pending W-OD-5_** | The approved invitee list, ≤ 5 |
| `L` | **_pending W-OD-5_** | `API_KEY_HOURLY_LIMIT` in `.env` |
| `D` | 14 | SR-10, fixed |
| `C_session` | **_pending W-OD-5_** | `LEARNING_SESSION_MAX_COST_USD` |
| `C_research` | **_pending W-OD-5_** | `MAX_COST_USD`, or 0 if research rights are withheld |
| **`worst_case_usd`** | **_pending W-OD-5_** | Computed above |
| Approved budget | **_pending W-OD-5_** | The number the owner is willing to lose |

**Every cell marked _pending_ is deliberately empty.** They are the numbers
W-OD-5 approves, and this runbook does not invent them. Fill the table in the
same commit that records the approval, and copy the filled table into
`evidence/gate-w2/pilot-record.md`.

### What the repository's current defaults would give

Not an approved configuration — an illustration of the formula's shape, using
the values committed in `src/config.py` and `deploy/pilot/env.example` today,
and the SR-09 cohort ceiling:

```
N = 5,  L = 20,  D = 14,  C_research = 2.00  (research rights granted)
worst_case_usd = 5 × 20 × 336 × 2.00 = 67,200
```

**That number is why this section exists.** At the shipped defaults the bound
is not a bound anyone would accept, which means W-OD-5 cannot approve "the
defaults" — it has to approve values. Solve the formula the other way round
instead: for an approved budget `B`,

```
L  ≤  B / (N × 24 × D × C_max)
```

so a $50 ceiling over five pilots with research rights at `MAX_COST_USD=2.00`
needs `L ≤ 0.0074` — i.e. **not reachable by tuning the hourly limit alone.**
The levers that actually move it are, in order of effect:

1. **Withhold `POST /research`** (OD-7's default posture: the expensive action
   stays operator-tier). `C_max` becomes `C_session`, a factor of 4 at today's
   defaults, and removes the single most expensive action from the cohort.
2. **Lower `C_session`.** ADR 0062 measured guided-session spend at
   $0.07–$0.17; the $0.50 default is protective headroom, not a target.
3. **Lower `L`.** A learner does not start twenty sessions an hour.
4. **Shorten `D`.** SR-10 fixes it at 14, so this one is not available.

The honest summary, and the sentence to carry into the W-OD-5 decision: *the
per-run caps bound one job, and nothing bounds the sum. Until L0-01 ships, the
sum is bounded by the account-level limit on the provider side and by the
cohort being five people who were invited by name.*

### The standing locks this sits under

- **Standing cost lock** (STATUS.md, 2026-08-30): no funded model run,
  deployment, public launch, or pilot invitation without fresh explicit owner
  approval. Local, mock, recorded-fixture, static and CI validation continue.
- **SR-09's re-trigger**: any cohort beyond 5, any public opening, or any
  scheduled (system-initiated) work re-triggers the F4 prerequisite. That is
  not a bigger pilot; it is a different decision, and the web tier refuses a
  sixth entry in the map rather than serving one.
- **The nightly eval workflow stays disabled.** It is a separate spend path
  and W-OD-1, not this decision.

---

## 4. Issuing a pilot

Nothing here mints a credential automatically. Every step is a human writing a
value into a file that is never committed.

### 4.1 Generate the two halves

```bash
# The edge credential. Record the plaintext in your password manager and
# send it to the pilot over a channel that is not email-plus-the-username.
docker run --rm -it caddy:2.11.4-alpine caddy hash-password

# The backend secret. Hex, so it is URL and header safe.
openssl rand -hex 32
```

### 4.2 Write the three places, in this order

The order matters: a pilot who can authenticate at the edge before the backend
knows their key gets a 503, and a pilot whose key exists before the edge does
cannot reach it at all. Backend first is the harmless direction.

1. **`deploy/pilot/pilot-keys.json`** — the backend keystore.

   ```json
   {
     "pilot-ada-2026-09": "sk_<the openssl value>"
   }
   ```

   Hot-reloaded: `KeystoreReloader` polls the file's mtime every
   `API_KEYS_RELOAD_INTERVAL_SEC` (default 30) and swaps the keystore without
   a restart. A parse error is logged and the *current* keystore is retained,
   so a bad edit does not lock the existing pilots out — check the `app`
   container's log for `keystore_reloader_iteration_failed` after every edit.

2. **`PILOT_PRINCIPAL_MAP` in `.env`** — the web tier's map. One JSON
   document, at most five entries.

   ```json
   {"pilot-ada": {"key_id": "pilot-ada-2026-09", "api_key": "sk_<the same value>"}}
   ```

   `key_id` must equal the keystore's name **exactly** — it is what lands on
   every row (ADR 0036) — and `api_key` its secret. A mismatch shows up as a
   pilot who authenticates at the edge and then gets 401 from the API.

   Not hot-reloaded: this is process environment, so it needs
   `docker compose ... up -d web`. Do the keystore edit first and this one
   second, and the window in between is a pilot who does not exist yet.

3. **`deploy/pilot/pilot-users.caddy`** — the edge credential.

   ```text
   pilot-ada $2a$14$<the caddy hash-password output>
   ```

   Then `docker compose ... up -d edge` (Caddy reads the file through
   `import` at config load, so it needs a reload, not just a file write).

### 4.3 Smoke-test before you send anything

```bash
curl -sS -u pilot-ada:<plaintext> https://<host>/api/healthz          # 200
curl -sS -u pilot-ada:<plaintext> https://<host>/api/conversations    # 200, []
curl -sS -o /dev/null -w '%{http_code}\n' https://<host>/api/healthz  # 401
```

The third line is the one people forget: it proves the edge is actually
gating, not that your credential works.

Then read the `web` container's log. Exactly one line per request:

```json
{"event":"pilot_principal","outcome":"resolved","user":"pilot-ada","key_id":"pilot-ada-2026-09"}
```

If `outcome` is anything else, the table in §7 says what it means. If the line
contains an `api_key` field, stop — that is a defect, not a configuration
problem, and `web/tests/pilotPrincipal.test.ts` should have caught it.

### 4.4 Record the onboarding date

**The 14-day clock is per pilot and starts on their onboarding date, not on
the cohort's.** Add the row to
[`evidence/gate-w2/pilot-record.md`](../../planning/07-learning-platform/evidence/gate-w2/pilot-record.md)
in the same sitting. A cohort onboarded over four days has four different
day-14s, and WO-W20's report is wrong in a way nobody can reconstruct later if
this is not written down at the time.

---

## 5. Revoking a pilot

**Revocation is a deletion, and it has a latency.**

1. **Delete the entry from `deploy/pilot/pilot-keys.json`.** Effective within
   `API_KEYS_RELOAD_INTERVAL_SEC` (default 30 s) — no restart. This is the
   step that actually stops spend, because it is the one FastAPI enforces.
   From this moment the pilot's requests are 401.
2. **Delete their line from `deploy/pilot/pilot-users.caddy`** and reload the
   edge. Now they cannot even reach the web tier.
3. **Delete their entry from `PILOT_PRINCIPAL_MAP`** and `up -d web`. Now the
   username maps to nothing and would 503 even if step 2 were undone.
4. **Do not reuse the `key_id`.** §1. Mark the register row revoked, with the
   date.

Steps 2 and 3 are cleanup; step 1 is the revocation. If you are in a hurry,
do step 1 and nothing else, then come back.

**Their data is not deleted by any of this.** The rows keyed on their `key_id`
remain. Account-level erasure is the WO-W02 promise and goes through
`progress_events`' deliberate `arxiv.progress_purge` door plus the profile and
conversation stores; it is a separate, explicit act, and the pilot should be
told which of the two happened.

---

## 6. The register

Keep it in
[`evidence/gate-w2/pilot-record.md`](../../planning/07-learning-platform/evidence/gate-w2/pilot-record.md).
It is the only mapping from `key_id` to human that exists anywhere, and §1's
never-reassign rule is unenforceable without it.

---

## 7. Reading the refusals

Every pilot-mode refusal is the same from outside — HTTP 503,
`{"detail": "pilot_principal_unresolved"}` — on purpose: an attacker must not
learn from a response whether a username exists. The *reason* is in the `web`
container's log, in the `pilot_principal` line's `outcome`.

| `outcome` | What happened | Fix |
|---|---|---|
| `resolved` | Nothing. This is the happy path. | — |
| `untrusted_topology` | The request carried no valid `X-Pilot-Edge-Key`, so it did not come through the edge. No username is logged, deliberately. | If it is a real pilot: `PILOT_EDGE_SECRET` differs between the `web` and `edge` services. If it is not: this is the guard working. |
| `username_missing` / `username_invalid` | The edge forwarded nothing, or something that is not a username. | Check `header_up X-Pilot-User {http.auth.user.id}` is present in the Caddyfile and that no `header_up -X-Pilot-User` was added beside it (deletions run last in Caddy and would erase it). |
| `unknown_username` | The edge authenticated somebody the map does not know. The username **is** logged — it came through the verified edge. | §4.2 step 2 was skipped, or the edge user and the map key are spelled differently. |
| `shared_key_also_set` | `ARXIV_API_KEY` is non-empty while the pilot map is configured. | Empty it. Two configured answers to "whose credential is this" is not a fallback chain. |
| `mode_value_invalid` | `PILOT_EDGE_AUTH` is set to something other than `on` or `off`. | Set it to `on`. `true`, `1` and `yes` are refused rather than silently ignored, so that "I turned it on" and "it is on" cannot disagree. |
| `map_*` | The map is missing, unparseable, empty, over five entries, or has a duplicate key or `key_id`. | The fault names which. The map is never quoted in the log — a parse error would quote a table of API keys. |
| `edge_secret_missing` / `edge_secret_too_short` | No shared secret, or under 32 characters. | `openssl rand -hex 32`. |

The proxy's own line carries `"outcome":"principal_unresolved"` for all of
them, which is how you tell a credential-seam 503 from an
`API_INTERNAL_BASE` one.

---

## 8. The note that goes to each pilot

Send this, adapted. It is written to be *true*, which matters more than it
being short: everything below is a property of the deployment as it exists,
and none of it is a promise about a version that does not.

> **What you are testing.** A guided-reading companion built around a research
> agent: it walks you through a paper, asks you questions while you read, and
> keeps a record of what you have worked through. We want to know whether you
> come back to it in the second week without anyone reminding you. We will not
> remind you — there is no notification of any kind in this build, on purpose.
>
> **How you sign in.** A username and password, in a browser dialog, over
> HTTPS. That is the whole of the login: there is no account page, no password
> reset, no profile picture, nothing to configure. Tell us and we will issue
> you a new one.
>
> **What is yours alone.** Your reading threads, your guided sessions, your
> learner profile, and your progress ledger. Nobody else in the pilot can see
> them, and the check is enforced in the backend on every request, not in the
> page.
>
> **What is shared, and this is deliberate.** The paper cache and the
> embedding cache. If you and another pilot read the same paper, the second
> read is faster because the first one is on disk. Those caches hold the
> paper's own text and vectors — not who fetched it, not what you asked about
> it, and not anything you wrote.
>
> **What we can see.** The operators can see everything in the database,
> including your threads and what you wrote in a session. This is a five-person
> pilot on a machine we run; treat it as you would a shared work notebook.
> Please do not put anything confidential or personal in it.
>
> **What the system records about you.** A profile made of things you told it,
> plus things it inferred from your sessions — and it labels which is which,
> always. It will never show you a "mastery" or "knowledge" percentage,
> because it cannot honestly compute one.
>
> **How long.** Fourteen days from the day you start. After that we will ask
> you a few questions and then either keep going or stop; either way we will
> tell you what happens to your data, and we can delete all of it on request.
>
> **What will be rough.** It costs us real money per session, so there are
> ceilings: a session can refuse to continue if it reaches one. The interface
> still calls itself a shared workspace in one or two places — ignore that, it
> is stale wording, your data really is separate. There is no mobile app.
>
> **How to reach us.** [channel]. If something looks wrong, it probably is;
> please say so.

Two things that note deliberately does **not** claim: that the pilot's data is
encrypted at rest beyond whatever the host provides, and that anyone other
than the operator can be prevented from reading it. Neither is true, so
neither is written.

---

## 9. Research-run rights (W-OD-5)

**Default posture: pilot keys are rate-limited exactly as any principal is
today, and `POST /research` is the expensive action.** ADR 0033/0037's
per-principal hourly limit applies to every pilot key with no special case,
and nothing in WO-W17 changes it.

Whether pilots keep `POST /research` at all is W-OD-5's to decide.
[`03` §8](../../planning/07-learning-platform/03-ARCHITECTURE-ROADMAP.md)'s
**OD-7** default is that the expensive action stays operator-tier, and §3's
arithmetic is the reason: `C_research` at `MAX_COST_USD=2.00` is four times
`C_session` at its default, and it is the term that makes the worst case
unpalatable.

There is no per-route permission model in this repository — `ApiKeyPrincipal`
carries a `key_id` and nothing else, and role-based access is a named
follow-up in `docs/security.md`. So "withhold research rights" is not a
setting. The three options, none of them free:

1. **Lower `MAX_COST_USD` toward `LEARNING_SESSION_MAX_COST_USD`.** One line,
   no code, and it caps rather than removes the action. It applies to the
   operator's own runs too, since the ceiling is per deployment.
2. **Do not surface `POST /research` to pilots and accept that the API allows
   it.** Honest only if written down; a pilot with `curl` is not prevented.
3. **Build the role model.** Not Phase W. It is MT-01/L0 work and its absence
   is why option 1 is the practical answer.

Record which one W-OD-5 chose, and the `MAX_COST_USD` value if it is option 1,
in `evidence/gate-w2/pilot-record.md`.

---

## 10. What this design does not defend

Carried from `deploy/pilot/README.md` so that the operator reads it here too:

- **Aggregate spend.** MT-01 **F4**. §3 is arithmetic, not a control.
- **Key custody at rest.** MT-01 **F3**. `pilot-keys.json` is cleartext.
- **A stable owner id.** MT-01 **F1**. §1 is the only control, and it is human.
- **CSRF.** Unchanged from `docs/security.md`; basic auth is not ambient the
  way a session cookie is, and MT-01 owns the fix.
- **Revocation latency.** MT-01 **T7**. Up to `API_KEYS_RELOAD_INTERVAL_SEC`
  seconds, by design; lower it if that matters more than the disk stats.
