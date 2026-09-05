# 0084. Log redaction is a secret rule, not a shape rule

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: Assurance lane (WO-D4)
- **Depends on**: ADR
  [0042](0042-api-guardrails-and-deploy-hygiene.md) (the leak that started it: a
  connection error whose *message* carried the URL),
  [0067](0067-correlation-context-and-log-contract.md) (the log
  contract — the allowlist, the size cap and the closed event registry
  all sit on top of `redact_text`),
  [0069](0069-property-based-testing.md) (the property tier this is
  proved in), [0072](0072-adversarial-safety-suite.md)
  (`CANARY_SECRETS`, which names `logging:redact_text` as the guard it
  measures)

## Context

ADR 0067 widened redaction from one rule with one call site to five
rules applied to every string the formatter emits. That was the right
move and it is the reason a password in a traceback no longer reaches
the index. But the five were chosen from **the shapes this repository
happened to emit**, not from the shapes a credential takes, and WO-D3
found the seam while moving `api_keys` to `SecretStr`. WO-C4 then
measured it:

| input | `redact_text` output |
|---|---|
| `sk-ant-api03-CANARYcanaryCANARY…` | `sk-***` |
| `gw_live_PROBEprobePROBEprobe00` | **`gw_live_PROBEprobePROBEprobe00`** |

A gateway or proxy credential — which buys exactly the same model calls
on exactly the same budget as the Anthropic key beside it — was not
covered by any of the five. It is not an edge case: `src/config.py`
already documents that `redact_text` "catches an Anthropic key and
misses a gateway or proxy credential that does not carry the prefix",
and `api_keys` exists precisely so this deployment can point at a
gateway.

The five rules were URL userinfo, `Bearer`, `sk-`, email addresses and
long base64-ish blobs. Read as a set, four of them describe *this
system's own traffic* and one is a catch-all for high entropy. Nothing
in the set describes the convention the rest of the industry issues
credentials under.

## Decision

**Add four rules, chosen as families rather than as vendors, and turn
the rule list into a named registry so the property tier can be
parametrised over it.**

`redact_text` is now `REDACTION_RULES` applied in order. Each rule is a
`(name, pattern, replacement)` triple. The names are not decoration:
`tests/property/test_property_redaction.py` derives its test ids from
that tuple, so a rule added without a generator fails a test rather
than shipping unproven. That is the mechanism this ADR most wants to
outlive its own rule list — the gap it closes was a *missing rule*, and
missing rules are exactly what a hand-maintained list of test cases
cannot see.

### The four new rules, and why each is in

**1. `environment_scoped_key` — `<issuer>_live_<body>`, `<issuer>_test_<body>`.**
The named gap, generalised. Stripe published this convention and
gateways, proxies and billing shims copied it wholesale: `gw_live_…`,
`sk_live_…`, `pk_test_…`, `rk_live_…` are one shape and not four
issuers. Written over the shape rather than a vendor list, because the
issuer half is the part that keeps changing and no list stays ahead of
it. The anchor is `_live_` / `_test_` immediately before an unbroken
run of sixteen alphanumerics, plus a digit or a case change in the
body.

**2. `vendor_prefixed_token` — a closed registry of issuer prefixes.**
`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`, `xoxb-`,
`xoxp-`, `xoxa-`, `xoxr-`, `xoxs-`, `xapp-`, `glpat-`, `whsec_`,
`dop_v1_`, `npm_`, `hf_`, `pypi-`, `AIza`. Closed on purpose: this
rule's precision is carried *entirely* by the literal prefix, and the
tempting generalisation — "a short prefix, a separator, a long body" —
matches half the identifiers in this repository. Two body alphabets,
because an issuer that segments its own tokens with `-` (Slack,
GitLab) needs the dash inside the body, and granting the dash to every
prefix would widen `hf_` far enough to swallow `hf_all-MiniLM-L6-v2` —
a model name this repository really does log.

**3. `aws_access_key_id` — `AKIA`/`ASIA`/`ABIA`/`ACCA` + sixteen uppercase.**
Its own rule rather than an entry in rule 2, because it is the one
prefixed credential with no separator and no lower case; folding it in
would have meant relaxing rule 2's body alphabet for every issuer to
accommodate one. The width is exact, which is what makes it safe.

**4. `json_web_token` — `eyJ….….…`.**
A bearer credential that arrives *without* the word "Bearer" — in a
cookie, a query string, a gateway's error body — so the existing
`bearer_token` rule cannot see it. `eyJ` is base64url for `{"`, and a
token that opens with it and carries two more dot-separated base64url
segments is a JOSE header, not prose. Base64url uses `-` and `_`, so
the blob rule could not have caught it either.

### What the rules keep

Every prefixed rule keeps its issuer prefix: `gw_live_***`, `ghp_***`,
`AKIA***`, `sk-***`. This is deliberate and it is why the new rules run
*ahead* of the blob rule rather than being left to it. `ghp_` plus
thirty-six mixed-case characters is also a forty-character base64-ish
run, so a blob rule reaching it first would emit `***[40 chars]` — the
secret is gone either way, but the line no longer names the console an
operator has to go and revoke at. A prefix is published, identical
across every token that issuer ever minted, and worth exactly as much
to an attacker as the word "GitHub".

This is the same ordering argument ADR 0067 made for putting URL
userinfo first, and the comment in `logging.py` says why in the same
words: a secret hidden under the wrong rule, with the wrong
replacement, is how a rule ends up looking correct in a test and wrong
in production.

### What is deliberately left out

**An entropy rule over unprefixed strings.** The obvious way to close
the gap "for good" — Shannon entropy, or "any 20+ character token with
mixed case" — is also the way to delete every arXiv id, DOI, content
digest, span id and model name in the log stream. An AWS *secret*
access key (forty unprefixed base64 characters) is genuinely
indistinguishable from a truncated content hash, and the honest answer
is that no text rule can tell them apart. It stays uncovered, and the
`base64_blob` rule catches it only when it is mixed-case with a digit.
**Rejected on precision.**

**A `password=` / `api_key=` keyword rule.** Attractive because it keys
on the label rather than the value, which is a genuinely different
axis. Rejected for two reasons. First, in this codebase secrets arrive
as `extra` dict *values*, and `_bound_value` scrubs each value on its
own — the key is a separate JSON field the text rules never see, so the
rule would fire on prose only, where the value is usually already
covered by shape. Second, it would take `token=QWxh…` away from the
blob rule, whose `***[78 chars]` reply is strictly more informative
than `token=***`. **Rejected as low-yield and lossy.**

**`Basic <base64>` alongside `Bearer`.** The guard that makes `Bearer`
safe against English — long, or short with a digit or a capital — does
not transfer to `basic`, which is an ordinary adjective that frequently
precedes a capitalised word: "basic Authorization header" would redact
to "basic *** header". `Basic` credentials shorter than forty
characters are therefore a **known gap**, recorded here rather than
closed badly. **Rejected on precision.**

**Bare `pk_` / `rk_` without the environment marker.** `pk_` is a
primary key at least as often as it is a publishable key. With the
`_live_` / `_test_` marker they are covered by rule 1; without it there
is no anchor. **Rejected on precision.**

**PEM private-key blocks.** Nothing in this system handles PEM, and the
body lines are usually caught by the blob rule. Not worth a rule until
something holds one. **Rejected as out of scope.**

## Alternatives considered

**Leave `redact_text` alone and rely on `SecretStr` (WO-D3).** Masking
at the type is the stronger guarantee and it is already done — but it
only protects values that pass through a `Settings` field. The leak
ADR 0042 recorded arrived through an exception *message*, from a
library that never saw our type. The two defences are complementary
and neither is a substitute; WO-D3's own ADR text says so.

**A published secret-scanning ruleset (gitleaks, detect-secrets,
trufflehog) vendored in.** ~150 rules, maintained by people who watch
issuer announcements. Rejected on three counts: it is a build-time
dependency in a hot path that runs on every log line (these rulesets
are written for a batch scanner, not a formatter); its rules are tuned
for *recall* over a git history, where a false positive costs a human
thirty seconds, whereas here it costs the log line forever; and it
cannot be reviewed — adopting 150 unread regexes into the one function
the log contract rests on is not a decision anyone can defend later.
The prefixes in rule 2 are drawn from the same public knowledge, read
and chosen.

**One rule per issuer.** Rejected: it makes the rule list grow without
bound, and it would have missed `gw_live_` for exactly the reason ADR
0067 missed it — nobody had heard of that issuer.

## Consequences

- **The measured defect is closed.** `gw_live_PROBEprobePROBEprobe00`
  → `gw_live_***`, asserted by name in `tests/test_log_redaction.py`.
- **Precision is measured, not asserted.** The four new rules were run
  over every tracked text line in the repository — 1,246,805 lines
  across 1,725 files. They changed **two** lines, both of which are the
  WO-D3 gateway-credential fixtures in `tests/test_config.py` and
  `tests/test_llm.py`. Zero false positives on the whole corpus.
- **The property tier is now parametrised over the rule set.** Three
  properties run per rule: the secret is destroyed; the secret comes
  back if that rule alone is removed (the mutation test, written down);
  and the issuer prefix survives. Two set-level tests close the loop —
  a rule with no generator fails, and a generator with no rule fails.
- **The inverse property is generated too.** arXiv ids in four forms,
  DOIs, model names, trace/span/job ids, digests, UUIDs, snake_case
  identifiers carrying `live` and `test` as words, and names wearing
  credential prefixes (`hf_hub_download`) are generated and asserted to
  come back byte-for-byte. A rule that eats a paper id is worse than
  the gap it closes, because it damages every line rather than one and
  it fails silently.
- **`redact_text`'s cost per line rises from five regex passes to
  nine.** Measured on a representative 204-character log line (event
  name, run and span ids, an arXiv id, a model name, a URL, prose):
  **13.0 µs → 20.7 µs, a factor of 1.6.** Taken on a loaded developer
  machine, so treat the ratio as the finding and the absolute numbers
  as an upper bound. This is the formatter's hot path, and it is a real
  cost — accepted because `_scrub` bounds its input first (truncate,
  *then* redact, per ADR 0067), so the cost is bounded per field at
  `MAX_EXTRA_VALUE_CHARS` rather than growing with the payload. If it
  ever needs to come down, the answer is a single alternation with
  named groups rather than dropping a rule.
- **Two known gaps are on the record** rather than quietly absent:
  short `Basic` credentials, and unprefixed high-entropy secrets such
  as an AWS secret access key.
- **`REDACTION_RULES` is public in `src/observability/logging.py` but
  is not re-exported** from `src/observability/__init__.py`. The D4
  fence exception was granted for that one file; the test imports the
  module path directly.
