# CI fixture correction — production packet unchanged

The first published head4675c4f had eight successful CI jobs, including the full
browser matrix, and one failed Python job. [Run42347008633](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/42347008633)
reported33failed/6635passed/1skipped (53e2e deselected). The new Opus and
measurement-reuse modules called the shared preview fixture without setting its
required offline-preview flag locally. The explicit flag on the original local
command masked that test-setup omission. Production correctly refused the
unconfigured preview; no production gate is loosened.

The correction adds a module-local autouse fixture to each of those two modules:
sentinel credential plus WORKSPACE_D5_OFFLINE=1, scoped to disposable tests.
[Both modules pass43tests](fixture-repair-tests.txt) with the **shell flag unset**.
The complete coverage/patch gate is rerun in that environment before republishing;
it passed6615tests/54skips in664.98s,94.61%total/97%patch, with all package floors met. [Full output](full-coverage-without-shell-optin.txt). No assertion, floor or test tier changes.

Application source and web trees remain exactly those of04945c6; the packet
85afa214bd4634ca27e668470257b9ecb53b2dfe87fa018ec17856e46729b35b and all four
historical measurement proofs are unchanged. The new publication changes tests
and verification documentation only. Final exact-head CI is distinct from the
failed first run and is bound by outputs/d5/opus-checker-v5/FINAL-PUBLICATION.json.
No provider/count contact, paid authorization, ledger mutation or new spend.
