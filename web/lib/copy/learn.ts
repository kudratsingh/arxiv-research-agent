export const LEARN = {
  navLabel: "Learning paths",
  landingEyebrow: "Guided reading",
  landingHeading: "Read papers with a path, not a pile.",
  landingBody:
    "Follow a deliberate paper sequence, use a briefing to orient yourself, then read the source on arXiv.",
  landingAction: "Explore the reading path",
  listEyebrow: "Path library",
  listHeading: "Choose what to read next",
  listBody:
    "Each path orders primary sources and explains why they belong together. The paper always stays the source of record.",
  listLoading: "Loading paths…",
  listEmptyHeading: "No paths are published",
  listEmptyBody: "There is no published reading sequence to show yet.",
  pathLabel: "Reading path",
  pathLoading: "Loading the path…",
  pathUnavailableHeading: "This path is unavailable",
  pathUnavailableBody:
    "Learning content is not available from the research service right now.",
  retry: "Try again",
  backToPaths: "All paths",
  openPath: "Open path",
  entriesLabel: "Paper sequence",
  papers: "papers",
  minutes: "minutes",
  updated: "Updated",
  fixtureLabel: "Fixture content",
  fixtureShort:
    "Demo scaffolding only. These placeholder briefings are not reviewed learning material.",
  noProgress: "No reading activity has been observed for this path.",
  progressSource: "Position is shown only from recorded session events.",
  observed: "Observed",
  notObserved: "Not yet observed",
  nextObserved: "Current observed position",
  briefingAvailable: "Briefing available",
  briefingUnavailable: "Briefing not yet available",
  openPaper: "Open on arXiv",
  whyHere: "Why it is here",
  vocabulary: "Vocabulary",
  attribution: "Source attribution",
  linkOutOnly:
    "This path links to arXiv and does not fetch or display paper full text.",
  sessionEyebrow: "Guided paper session",
  sessionLoading: "Reattaching to your reading session…",
  sessionUnavailableHeading: "This reading session is unavailable",
  sessionUnavailableBody:
    "The session may have expired, belong to another reader, or be turned off. No distinction is exposed.",
  backToPath: "Back to the reading path",
  sourceLabel: "Primary source",
  passageLabel: "Briefing companion",
  passageEmpty: "No briefing companion is available for this paper.",
  conversationLabel: "Reading margin",
  tutorLabel: "Tutor note",
  learnerLabel: "Your note",
  currentTurnLabel: "Your turn",
  replyLabel: "Write your response",
  replyHint:
    "Use your own words. Uncertainty is useful evidence and is not scored as failure.",
  submitTurn: "Continue the session",
  submittingTurn: "Recording your response…",
  endSession: "End after this response",
  workingHeading: "The tutor is preparing the next prompt",
  workingBody:
    "No percentage or completion estimate is shown. The next observed checkpoint will appear when the service publishes it.",
  reconnecting: "Connection interrupted. The browser is reattaching to the same session.",
  resumed: "Session restored from its durable checkpoint.",
  transcriptUnavailable:
    "The session is available, but its saved reading margin could not be loaded. Nothing has been reconstructed from stream events.",
  costCapHeading: "Session cost limit reached",
  costCapRefused:
    "The next model call was refused before spending beyond this session’s limit.",
  costCapDegraded:
    "The session closed with a bounded fallback instead of spending beyond its limit.",
  unassessedHeading: "No assessment was recorded",
  unassessedBody:
    "This is an explicit missing assessment, not a grade or a claim of mastery.",
  recordedUngraded:
    "Your explain-back was saved as evidence. It has not been turned into a grade.",
  completeHeading: "Session complete",
  completeAdvance:
    "This session advanced one guided reading and preserved your own explain-back as evidence.",
  failedHeading: "The session stopped",
  failedBody:
    "Your saved reading margin remains visible when available. The service did not claim completion.",
  emptyTurn: "The server has not published a learner turn yet.",
  retrySession: "Try to reattach",
} as const;
