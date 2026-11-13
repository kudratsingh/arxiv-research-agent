# Independent offline package cross-check

This is a reading addendum to the original [verification record](evidence/consolidated-campaign-v13/VERIFICATION.md). It does not change the frozen package or grant execution authority. Review was read-only; no provider or token-count contacts, financial mutations, or remote state changes were made.

## Checked identities

- Qualification application: `a3cf3d7c579ec61cd628d758b341c34daaad3dc0`.
- First publication: `6ffd54e8b6b492bb0dc566a50e35874e1f7a7a9d`.
- Packet: `97d24567bc98753122315f135a621eb886cebb2b81c32eb5762572589f037e08`.
- Scope: `d5-97d24567bc98753122315f13`.
- Capacity and exception proposal: `c582b5f64dfb515ca079f17a179365208f00dd1f098fa2c081f46aeec4d8b028`.
- Answerability matrix: `fdf88e73d7a5691a9cc503f89cdd82dadb868b82344f416afb7032c3a485a8a5`.

## Checks and findings

The 21 file hashes listed in `FILE-CHECKSUMS.json` matched their package files. The offline `src.workspace.d5_campaign verify` command passed and reported that no authority or contacts were created. Packet and owner-authorization template approval flags were false. The 24 matrix rows formed unique case/part pairs, three for each of eight evaluation cases; each exact request string and each selected evidence handle, work ID, version ID, material ID, source hash, parser revision, scope and span ID appeared in its corresponding compiled input. The retained-support and missing-information reference prose was absent from compiled inputs and blinded probe payloads; generic schema words also occur in payloads and are not by themselves evidence of label leakage. Local Markdown links in the reviewed plan and package documents resolved.

The custody summary records 28,519 verified manifest entries and no unavailable captured versions. The package records 28,233 unique original/version pairs, five reverified links and ten files. The three hashes binding the custody summary to its manifests and critical-originals receipt matched. These checks inspect receipts and selected bindings, not a new rehash of the archive. The exact historical 284-path list was not supplied; its membership and any claimed cancellation of that particular deletion queue remain unverified.

No concrete packet or scoring correctness defect was demonstrated in this limited review. Three clarifications matter when reading the records:

1. The matrix's `extraction` origin tags are proposed machine-reference gap categories. They do not themselves prove that an extraction attempt failed. This is an annotation caveat, not a demonstrated scoring defect.
2. The preservation receipt establishes **zero new evidence copies** in this verification. Existing archives overlap; it does not establish that there are zero duplicate copies in existing storage.
3. First publication CI run `43382685582` had eight successful jobs and Python cancelled at its aggregate 35-minute bound. Its coverage test progress reached 99%; coverage did not complete, and the unfinished Python gate did not pass. The cancellation annotation and logs are retained in the permanent publication evidence.

The packet verifier checks the frozen structure and seals. It does not independently establish scientific truth, quality of machine-reference judgments, or correctness of every evidence quote and Unicode offset. This review did not independently recalculate every selected quote or offset, rehash 28,000 files, re-run broad tests, inspect or alter the live database, or establish remote CI success for a later head. Human qualification and owner usefulness remain unmeasured. The historical 284-list limitation remains open.

All rights reserved. No license or reuse permission is granted.
