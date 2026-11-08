# Evaluator-only archived question seeds

Seven matched-set seeds: three regressions and four fresh question sets over
archived real public evidence. No new provider output or human judgment exists.
The seed metadata is NEVER a checker payload. Full drafts and selected passage
identity are derived from archived v7r2 checker requests; each matched set varies
only one question slot. Fresh sets use a fixed scored-claim subset to distinguish
source-supported but unscored premises from unsupported premises. The original
provider responses, scopes, costs and 3/8 Stage C score remain untouched.

Regression seeds cover the autonomous-discovery flag, the previously passed
ablation question and a derived ReAct hedge-drop question. The derived question
is synthetic and does not claim to be an observed provider error. Proposed
expected labels require independent review, especially the ablation ambiguity.

`question_premises.build` exports opaque shuffled packets and blank worksheets.
The salt, variant names, matching key and proposed dispositions remain in local
evaluator-only files, excluded from checker requests. Tests use explicitly
synthetic salts and labels. Live reviewer labels must be locked before viewing
any new checker verdict and remain blank in the delivered owner worksheet.
