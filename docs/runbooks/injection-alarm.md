# Runbook — injection alarm

Content this system ingested may be steering it. The reader consumes
paper abstracts and full-text chunks from arXiv; the planner consumes
prior-report context; the tutor and the profile serializer consume
learner-authored text. All four are untrusted, and since the supervisor
loop landed, the reader's output also feeds **control tokens the
supervisor reads directly** — which turned prompt injection from "the
report is wrong" into "the loop is redirected".

Start with the honest limitation, because it changes how you read
everything below.

> **This alarm is log-only, and it is a proxy.** No instrument in this
> repository counts injection attempts, contained or otherwise. The
> containment SLO in [`../reliability.md`](../reliability.md) §3 is a
> **build-time** objective, measured by `pytest -m security` against a
> fixture corpus, not a runtime one. What follows are the runtime
> signals that *correlate* with a successful steer. A quiet log is not
> evidence of containment.

## 1. The signal

| Signal | Where | What it means |
|---|---|---|
| `route_after_supervisor_unknown_action_endpoint` | log, WARNING | **The loudest one.** The supervisor produced a `next_action` that maps to no node. The action vocabulary is a closed set and the model is the only writer into it, so this is either a stale checkpoint from a build with different flags, or the loop being redirected. The graph routes to `END` either way — it cannot wedge — but it also cannot tell you which of the two happened. |
| `route_after_supervisor_disabled_action_endpoint` | log, WARNING | The action exists but this build has it behind a disabled flag. Same two causes, and a stale checkpoint is the likelier one. |
| `supervisor_invalid_action_fallback` | log | The supervisor's own guard fired before routing. |
| `critic_*_unparseable`, `planner_response_*`, `synthesizer_response_*`, `session_tutor_unparseable`, `session_check_in_unparseable` | log | Structured-output contract failures. Ordinary at a low rate; the second-loudest injection tell at a high one, because a payload that talks a node out of its output contract produces exactly this. |
| `session_tutor_safe_reask`, `session_check_in_safe_fallback` | log | A guided-session node refused its own output and fell back to a safe one. |
| `synthesizer_citations_dropped`, `revision_target_undispatchable` | log | Output that referenced things that do not exist. |
| `pdf_url_rejected_*`, `pdf_download_not_a_pdf` | log | The SSRF guards refusing a fetch. Not injection, but the same attacker in a different mood, and they share a timeline. |
| `gen_ai.invoke_agent.tool_calls`, `gen_ai.invoke_agent.inference_calls` | metric | Per-invocation call counts by agent. A step change is the shape of a loop that stopped terminating, which is what a successful steer often looks like from outside. |

Alarms: `SupervisorReceivedAnUnknownAction`,
`ReaderControlOutputUnparseable` in
[`log-alerts.yml`](../../deploy/observability/log-alerts.yml).

## 2. The first three commands

```bash
# 1. What action did the supervisor try to route to? The value is the finding.
dc logs --since 24h app | jq -c 'select(.message | startswith("route_after_supervisor")) | {ts, message, action, job_id, run_id}'

# 2. Is the isolation actually on in this deployment? It is a flag.
dc exec app python -c "from src.config import settings; print(settings.enable_prompt_isolation, settings.enable_verifier, settings.max_iterations)"

# 3. Everything that job did, in order. `run_id` and `job_id` are on every line.
dc logs --since 24h app | jq -c 'select(.job_id == "<job_id>") | {ts, level, message}'
```

Command 1 first because the `action` field is the entire diagnosis in
one string. A plausible-looking action name (`verify`, `revise`) that
happens to be disabled in this build is a stale checkpoint and not an
attack. An action that reads like a *sentence* — anything with a space,
an imperative verb, quoted text — is a model that was told what to
write, and that is the incident.

Command 2 second because `ENABLE_PROMPT_ISOLATION` is a flag, and a
deployment running with it off has none of ADR 0020's defences: no
delimiters, no data-not-instructions system instruction, and no
post-call sanitizers on the control fields.

## 3. Containment

**Turn the isolation on if it is off.** Nothing else matters until it is.

```bash
# in .env: ENABLE_PROMPT_ISOLATION=true
dc up -d app
```

**Then decide whether this is one job or a campaign.** One job: let it
end. It has already routed to `END` and the sanitizers have already
blanked the control fields — that is the defence working, and the
alarm's job was to tell you it was exercised.

A campaign — repeated, from one principal, or across many jobs — is
contained at the principal:

```bash
# Identify the principal. It is a salted hash, never the key id.
dc logs --since 24h app | jq -c 'select(.message | startswith("route_after_supervisor")) | .principal_hash' | sort | uniq -c
```

Then revoke that key. [`pilot.md`](pilot.md) §5 is the procedure, and
its first step — deleting the entry from the keystore — is the one that
actually stops it, within `API_KEYS_RELOAD_INTERVAL_SEC`. Steps 2 and 3
are cleanup.

If the source is a **paper** rather than a principal — the same arXiv id
across several jobs — there is no per-paper block list in this
repository. The containment is `dc stop app`, and the finding is that a
block list is missing.

**Preserve the evidence before restarting anything.** Log retention here
is Docker's, and a restart plus a log rotation loses the only record
there is:

```bash
dc logs --since 24h app > /tmp/injection-$(date +%s).jsonl
```

Note what that file contains before you move it anywhere: with
`LOG_CAPTURE_USER_CONTENT` or
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` turned on it holds
paper text, research queries and learner writing. Both default to off,
which is the reason they default to off.

## 4. Rollback

Injection is an input, not a release, so there is usually nothing to
roll back. The two exceptions:

- **A prompt changed.** Prompts are code here. If the alarm started at a
  deploy that touched `src/agents/*` or `src/security/prompt_isolation.py`,
  roll back to the previous SHA and re-run the safety suite against the
  change before deploying it again:

  ```bash
  git checkout --detach <previous-release-commit>
  dc up --build -d app
  ```

- **A flag changed.** `ENABLE_PROMPT_ISOLATION`, `ENABLE_VERIFIER`, or a
  model id. Restore it and restart.

Then run the suite that is supposed to catch this class, at zero spend:

```bash
OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false ANTHROPIC_API_KEY=local-preview-disabled \
  .venv/bin/python -m pytest -m security -q
```

If it passes and the incident was real, the finding is a corpus gap: add
the payload as a fixture. That is the mechanism by which this runbook
makes the next occurrence a test failure instead of an incident.

## 5. What this runbook does not cover

- **Detection.** There is no injection detector, no classifier and no
  per-attempt counter. Everything above is a downstream symptom, and the
  containment SLO is measured offline against a fixed corpus. The
  missing instrument is named in
  [`../reliability.md`](../reliability.md) §7.
- **Exfiltration.** The zero-tolerance classes — a secret leaving the
  process, an unauthorised tool call, egress to a non-allowlisted host —
  are enforced by the SSRF guards and the closed tool set and are
  asserted by `pytest -m security`. If one of them *has* happened, this
  is not the page: it is a security incident and the key material is
  compromised.
- **Cross-principal leakage.** Enforced by `_check_ownership` on every
  request and asserted by `tests/test_per_principal_scoping.py`. The API
  answers identically for "does not exist" and "belongs to somebody
  else", on purpose — which also means a leak attempt is
  indistinguishable from a 404 in the logs, and there is no runtime
  signal for it at all.
- **Whether the report was influenced.** A steer that produced a plausible
  wrong report leaves no marker anywhere. That is the honest ceiling on
  this page.
