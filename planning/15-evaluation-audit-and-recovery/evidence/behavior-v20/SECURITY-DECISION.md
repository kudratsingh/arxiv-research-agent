# Optional combined gate-resolution decision — not active

The existing C4 gate is red on the exact23development chains documented in [CI-AUDIT-DECISION-v20](../../CI-AUDIT-DECISION-v20.md). Picomatch4.0.7 remains the latest observed release. Available Next/Vitest patches were installed and tested; no patched matcher release was observed. Automatic approval review refused adding a persistent allowlist exception without explicit owner risk acceptance. No exception was installed, and neither this file nor the provider approval waives the gate.

To avoid another routine approval cycle, the owner may append this separate, explicit risk decision to the consolidated campaign approval. It permits only a narrowly dated policy change and still requires a new exact-head green CI result before provider execution. It is not a security fix or deployment permission. Alternatively keep dispatch stopped until a compatible upstream fix is available.

```text
I explicitly accept the unresolved development-tooling risk for only the23
exact package/advisory/path entries listed in CI-AUDIT-DECISION-v20.md.
I approve using the existing C4 exception mechanism for those exact entries,
with expiry no later than2026-11-21, a justification/link to this decision,
and no exception for production high/critical findings or any new/stale/mismatched
advisory. Preserve the zero-high/critical production audit and all other checks.
Do not change runtime provider/evidence/scoring code or reseal the v20 packet.
Obtain all required exact-published-head CI checks green after that explicit
policy change, then execute only the separately named consolidated v20 scope
within its existing ceilings, expiry and stop rules. If anything else fails,
stop rather than broadening this exception. No merge or deployment.
```

This text is proposed approval wording, not recorded authority. Without the explicit owner choice there is no permission to install an exception, activate a grant or contact a provider. Next's vendored matcher is outside npm's dependency graph, so zero production audit findings do not establish absence of all affected code. The evaluation process is qualification-only Python; the frontend is not being deployed. Do not treat that isolation as settlement of the vulnerability.
