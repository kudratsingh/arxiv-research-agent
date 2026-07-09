# Security

## Threat model

The workflow ingests arXiv PDFs. That's untrusted content: anyone
can publish a paper, and the reader passes paper text directly into
a Claude call whose output the workflow acts on. Sprint 2 landed a
supervisor loop that reads reader-emitted control tokens, which
made prompt injection a **workflow-control** risk on top of the
existing "the report is wrong" risk.

Attackers we defend against:

- A malicious arXiv paper with a jailbreak in its abstract or full
  text, aiming to redirect the supervisor's next action, stop the
  loop early, or smuggle instructions into the report via evidence
  claims.

Not in scope:

- Content-safety filtering (offensive text in abstracts).
- Injection via user-supplied query strings (short, controlled).
- Compromised Claude / Anthropic infrastructure.
- Compromised arXiv delivery infrastructure (the workflow does not
  cryptographically verify PDFs).

## Defenses

### Reader prompt-injection isolation (ADR 0020)

Behind `settings.enable_prompt_isolation` (default off; **flip on
whenever `enable_supervisor` is on**). Three layers:

1. **Delimiter isolation**. Paper-derived text (abstract + ranked
   chunks) is wrapped in `<untrusted_paper_text>...</untrusted_paper_text>`
   tags in the reader's user prompt. Close tags in the content are
   escaped so a paper can't terminate the wrapper.
2. **Explicit system-prompt instruction**. `ISOLATION_SYSTEM_INSTRUCTION`
   is prepended to the reader's system prompt when the flag is on.
   It names the delimiter tags and the exact control fields it's
   protecting (`analysis_complete`, `request_more_sections`,
   `missing_context`).
3. **Output sanitization on control fields**.
   `sanitize_control_string(missing_context)` trims / caps at 300
   chars / blanks on jailbreak markers.
   `sanitize_section_names(request_more_sections)` drops entries
   longer than 50 chars, entries with disallowed characters, and
   entries with jailbreak markers. `_parse_claim` runs the same
   filter on `EvidenceClaim.claim` and drops the claim on match.

Source: `src/security/prompt_isolation.py`. Wired at
`src/agents/reader.py::_analyze_paper` and
`src/agents/reader.py::_parse_recovery_signal` /
`src/agents/reader.py::_parse_claim`.

**Not sanitized**: `EvidenceClaim.source_text` (the verifier judges
against it; must be verbatim), `key_findings` / `methodology` /
`results_summary` / `limitations` (flow to synthesizer, not to
supervisor control tokens). These are follow-up work.

### Adversarial tests

`tests/test_reader_isolation.py` exercises canned jailbreak strings
in the abstract, in the LLM's response (simulating a compromised
model), and in evidence claims. Every attack surface is verified
with both flag positions so the pre-isolation baseline behavior is
also documented.

## Follow-ups

- Extend isolation into the synthesizer and verifier prompts (they
  read `EvidenceClaim.source_text` and paper analyses; both are
  vectors even with the reader defended).
- Default `enable_prompt_isolation` on once Sprint 4 baseline
  numbers exist with it enabled.
- Structured logging / metrics on sanitization drops so we can see
  how often the filter fires in production.
- Content-classifier-based rejection at ingest (an extra Claude
  call per paper; scope for Sprint 5+ if the deployment model
  justifies the cost).
