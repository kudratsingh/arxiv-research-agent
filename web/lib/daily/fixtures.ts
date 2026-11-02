/** Fictional material from the direction kit's acceptance scenario, never news. */
export type WorkspaceItem = {
  id: string;
  title: string;
  kind: string;
  source: string;
  version: string;
  published: string;
  scope: "abstract" | "excerpt" | "metadata";
  topics: string[];
  change: string;
  reason: string;
  caveat: string;
  abstract: string;
  prompt: string;
  nextAction: string;
};

export const ITEMS: WorkspaceItem[] = [
  {
    id: "corpus-shift",
    title: "When the corpus changes, what are we actually measuring?",
    kind: "Paper",
    source: "arXiv · fictional preprint",
    version: "v1",
    published: "2 November 2026",
    scope: "abstract",
    topics: ["ml:retrieval-and-memory", "ml:evaluation-and-responsible-ml"],
    change: "A different evaluation setting for retrieval systems.",
    reason:
      "Connects retrieval evaluation to your question about a small, controlled experiment.",
    caveat:
      "Only the abstract is available. The experimental controls have not been inspected.",
    abstract:
      "Comparisons of retrieval systems can depend on the document collection available at evaluation time. We describe a protocol that keeps a corpus snapshot and a query set fixed while changing the ranking method. This separates changes in ranking from changes in the material being retrieved. We discuss limitations when relevance labels or source versions change between runs.",
    prompt: "Does my own evaluation keep the document set fixed?",
    nextAction: "Pin a corpus, query set and scoring rule before varying one ranking choice. Hardware feasibility remains unknown.",
  },
  {
    id: "inference-release",
    title: "From inference paper to implementation",
    kind: "Implementation",
    source: "Lab release · fictional announcement",
    version: "release 0.1",
    published: "1 November 2026",
    scope: "metadata",
    topics: ["ml:ml-systems-and-efficiency"],
    change: "A reference implementation is now listed alongside the paper.",
    reason:
      "Matches efficient inference and your interest in small implementation experiments.",
    caveat:
      "Code availability is not a reproduction. Hardware and license requirements remain unknown.",
    abstract:
      "This fictional release record links an inference method to a reference implementation. No repository has been fetched or executed, and no performance result has been independently checked.",
    prompt: "What would I need to test the smallest part of this method?",
    nextAction: "Inspect the license, dependencies and hardware requirements before proposing a small benchmark. No repository code has been fetched or executed.",
  },
  {
    id: "measurement",
    title: "A useful detour: uncertainty is part of the measurement",
    kind: "Perspective",
    source: "Measurement journal · fictional excerpt",
    version: "original",
    published: "30 October 2026",
    scope: "excerpt",
    topics: ["study:26/applied-mathematics"],
    change: "An adjacent perspective on evaluation design.",
    reason:
      "Exploration: connects scientific measurement to comparing ML systems.",
    caveat:
      "This is a suggested connection, not evidence that the two fields use interchangeable methods.",
    abstract:
      "A measurement is interpreted through the conditions under which it was made. Reporting variation alongside a central estimate helps separate a stable effect from changes in the measurement procedure. Transferring this idea to a new setting requires checking which assumptions still hold.",
    prompt:
      "Which sources of variation should my evaluation report separately?",
    nextAction:
      "List the sources of variation in your measurement and which conditions you can hold fixed. Check the transfer assumptions before borrowing a procedure.",
  },
];

export const PRESET = [
  "ml:retrieval-and-memory",
  "ml:evaluation-and-responsible-ml",
  "ml:ml-systems-and-efficiency",
];
export const SOURCE_CHECKS = [
  { name: "arXiv · ML", status: "Sample check available", ok: true },
  { name: "arXiv · AI", status: "Sample check available", ok: true },
  { name: "arXiv · language", status: "Sample check available", ok: true },
  { name: "Lab release feed", status: "Sample check available", ok: true },
  { name: "Measurement journal", status: "Sample check available", ok: true },
  {
    name: "Research blog",
    status: "Sample timeout · interval not checked",
    ok: false,
  },
];
