# Example briefing and deep dive

**Design fixture only.** The papers, releases, counts and findings below are
fictional. They define behavior for a prototype and acceptance tests; they
are not a current-news report or a research recommendation.

## Lens and morning state

The user follows efficient inference, retrieval evaluation and ML systems.
Their project question is “Which small experiment would tell me whether a
retrieval change helps?” Reading mode: 15 minutes. Available hardware has not
been supplied. One of six configured sources failed its latest check.

> Your briefing since the last visit
>
> Five of six sources checked. One feed is delayed; retry details are available.
> Three new clusters match your interests. There is also an update to a saved paper.

| Item | Why it appeared | Evidence status | Useful action |
|---|---|---|---|
| A paper on evaluation under a changed retrieval corpus | Matches the project question and retrieval-evaluation topic | Preprint; source abstract available; full text not yet processed | Read the evaluation conditions |
| Official implementation for a previously saved inference paper | New code release linked to an existing work | Official code availability; results not independently reproduced | Inspect requirements and baseline command |
| A scientific measurement article | Adjacent discovery: uncertainty connects to evaluation design | Publisher metadata and excerpt only | Save or dismiss the connection |
| v2 of a saved paper | Source version changed after the user's note | Change details awaiting comparison | Compare versions before reusing the old summary |

The first card uses an attributed source abstract, not a generated summary.
“Generate a source-backed summary” is disabled until an approved model budget
exists. The original source and note editor remain usable.

## Selected deep dive after generation is enabled

User: “Explain what has to remain fixed to compare these retrieval systems.”

The reader shows the active scope: this work, version 1, selected methods and
results excerpts. A generated response might identify the corpus snapshot,
query set and scoring rule, each with a link to an actually retained passage.
If the passage does not specify a variable, the answer records that absence.
It does not invent a benchmark name or measured improvement.

| Entry | Kind | Required evidence |
|---|---|---|
| The source used one corpus snapshot for both conditions | Source-reported method | Retained span with section/page or paragraph anchor |
| Repeating this comparison after the corpus changes may alter attribution | Derived inference | Link to method premises plus an explicit inference label |
| Our own corpus freshness is affecting the result | Hypothesis | Unproven; linked to a proposed test, not an asserted result |

User pins: “Does my own evaluation keep the document set fixed?” The question
appears in the project notebook and in tomorrow's Continue section. It is not
automatically scheduled as a new paid research job.

## Build brief

Goal: isolate whether retrieval-ranking changes improve the selected test set.
Save a fixed corpus/query snapshot, baseline ranking and evaluation procedure.
Vary one ranking choice. Record seeds, parameters, relevant-source labels,
failure cases and the cost of each run. Hardware requirement is **unknown**
until implementation/data sizes are supplied. A small subset is proposed first.

Acceptance: the user can reproduce both runs from pinned inputs and inspect
the cases that improve or regress. Stopping condition: the planned time or
budget is reached, or corpus/label changes invalidate the comparison. No code
is executed by the research app in this release.

## Next visit and failure cases

Reopening restores the source version, selection, question and note. A source
failure leaves them intact. If v2 arrives, the old answer is labelled as based
on v1 and can be regenerated as a separate revision after approval. A failed
model job retains the note and any paid partial output; retry does not blindly
repeat completed work. A week away produces one bounded catch-up view with
versions/corrections prioritized, rather than a stack of seven notifications.
