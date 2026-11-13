# Exact credential-boundary property repair

The mandatory local gate after the theme fix reached7147pass/1fail/54skip,
53separateE2Edeselected in1661.69s, with94.39%project coverage. Publication
stopped. The captured Hypothesis example is preserved unchanged in the
permanent gate log; [this reproduction](REDACTION-ORACLE-REPRODUCTION.json)
binds its original test source and the unchanged production redactors.

The password was postgres, which also appears in the public postgresql scheme.
Both implementations correctly removed all userinfo, but the global substring
assertion mistook the retained diagnostic scheme for a secret leak.

The properties now require the exact independently constructed masked URL,
including all userinfo removal and unchanged scheme, host, port, path and
surrounding prose. This is stricter than checking a password substring. The
mutation control requires the entire credential-bearing URL to survive when
its specific rule is removed. Explicit scheme/password and host/password
collisions prevent regressions, and generator assumptions excluding colliding
hosts/usernames were removed so that these cases remain covered.

Focused redaction and property suites:97pass in7.42s; Ruff passes. No production
redactor, qualification producer, packet, source, schema, threshold or historical
result changed. This is a test-oracle correction, not evidence of a newly fixed
production disclosure. The complete gate is rerun before any push; its final
result and subsequent exact-head CI are recorded separately.

Private permanent logs and original coverage XML are under
`~/Machine-Learning-Projects/arxiv-evidence/d5-campaign-20261112/ci/theme-repair/`.
No failed evidence was removed. No provider or count contact, authority,
accounting mutation or new spend occurred.
