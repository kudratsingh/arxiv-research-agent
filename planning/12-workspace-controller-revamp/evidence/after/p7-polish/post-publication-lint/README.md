# Publication-lint correction after the frozen G7 evidence

The repository-wide Ruff check found 128 style errors in three inherited P6
helpers, four active P7 helpers and one archived failed video harness. This
metadata/script-only correction is based on `7cb0fe0`; application `6b2eccf`
and its web/backend/test trees remain unchanged. No helper was imported or
executed, and no seed, teardown, service, provider or database action ran.

## Original evidence remains available

The original [browser manifest](../browser-artifact-hashes.json),
[handoff hashes](../handoff-hashes.json), [browser README](../README.md), summary
and runtime receipts retain their exact bytes. Their helper entries describe
**captured original scripts**, not the later style-corrected active scripts.
[Original-path mapping](original-python-mapping.json) records all eight original
paths, byte counts, SHA-256 hashes and exact `.py.txt` archive paths. Seven active
scripts remain at their original paths. The failed `harness-at-capture.py` is
archival only and is now `harness-at-capture.py.txt` with identical bytes.

[Verification manifest](verification.json) resolves every original browser entry
through that mapping: **all 1,244 entries match their original hash and size**.
It also gives each active helper's new hash and normalized-AST hash. This is a
separate post-lint receipt; the original manifest has not been silently refreshed.
The seven separately bound handoff files, including README hash
`71c8980fb320a480cb7392bdd46483519120176e5bf4e4216100e2c79d4e337e`,
are checked unchanged in [integration checks](integration-checks.json).

## Bounded style and semantic checks

The seven active helpers have multiline statements and sorted import blocks.
The three guarded fixture scripts use an unconditional `main()` execution
boundary so imports stay in the same guarded execution sequence. No import moves
across an environment, database-ownership or source-root guard. Contiguous import
blocks are sorted; all other statement/call/guard ordering stays the same.
Python 3.11's `datetime.UTC` replaces the equivalent `datetime.timezone.utc`;
one `subprocess.run` uses `capture_output=True` instead of two `PIPE` keywords.
Arguments, filenames, ports, principals, ownership comments, requests, database
predicates, writes and teardown assertions are unchanged.

The [read-only verifier](verify.py) parses and compiles scripts without importing
or running them. It compares ASTs after only the declared execution-wrapper,
contiguous-import, UTC-alias and subprocess-capture normalizations. **All seven
active ASTs match** their archived originals. This is a structural check plus
review of this bounded style delta, not a claim of fresh fixture/runtime execution.
The one failed harness is never rewritten or promoted.

- [Repository-wide Ruff](ruff-check.log): `locked-python -m ruff check .`, exit 0.
- [Compiler check](py-compile.log): seven active helpers plus verifier, exit 0;
  bytecode is confined to `/private/tmp`.
- [AST/hash command](verification-command.log): seven ASTs and all original
  browser hashes pass.
- [Documentation/hygiene](documented-claims-and-hygiene.log): **66/66 in 9.15 s**.
- [Source/link integration receipt](integration-checks.json): exact application
  and backend equivalence, local Markdown link scope and unchanged handoff hashes.

No Ruff rule, exclusion, coverage floor, route budget or application asset changes.
G7 acceptance still belongs to application `6b2eccf`; G8 publication and exact
pushed-head CI remain pending root integration. No frontend/browser rerun is
claimed for this pure helper-style correction. Raw logs and original `.py.txt`
archives remain byte-exact, including original whitespace.
