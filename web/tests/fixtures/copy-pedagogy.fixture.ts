/**
 * THE PLANTED FIXTURE. THIS FILE IS SUPPOSED TO FAIL (WO-W14 criterion 2).
 *
 * "The forbidden-string suite fails on a planted '87% mastered' fixture in
 * any `(learn)` copy module — the gate is proven by a fixture that must
 * fail." That is the technique WO-01 of the revamp established and
 * `tests/fixtures/copy-inline.fixture.tsx` still uses: a rule nobody has
 * seen fire is a comment, so the repository commits a real file that really
 * violates it and a test asserts the exact violations.
 *
 * WHAT IT IS. A copy module shaped exactly like `lib/copy/ledger.ts` — an
 * `as const` block of strings plus a composer — written the way a learning
 * surface would be written by somebody who had not read
 * `01-LEARNING-AGENT.md` §4.1. Every string here is the kind of sentence
 * the edtech industry ships by default, which is the point: none of them
 * looks like a mistake.
 *
 * WHY IT LIVES OUTSIDE `lib/copy/`. `npm run lint` walks `app/`,
 * `components/` and `lib/` only, and the whole `lib/copy/` directory is
 * walked by the gate itself — a file in there would fail the real suite
 * rather than being *asserted* to fail by a test that reports what it
 * caught. `tests/fixtures/copy-*.fixture.*` is where this repository
 * already keeps its deliberately-failing files.
 *
 * NOTHING IMPORTS THIS BUT `tests/copy/forbidden.test.ts`.
 */

/** The half a deny-list of §5.5 alone would let through unchanged. */
export const PLANTED_PEDAGOGY = {
  headline: "87% mastered",
  scoreLine: "Your knowledge score for Transformers is 4.2 out of 5.",
  unlocked: "You unlocked the next paper. Keep it up!",
  streak: "6-day streak — don't break it now.",
  xp: "You earned 120 XP this week.",
  proficiency: "Proficiency: intermediate.",
  badge: "Attention badge awarded — download your certificate.",
  dashboard: "Back to the learning dashboard",
  graded: "This explain-back was graded 8/10.",
} as const;

/**
 * A composed form, because the gate drives functions as well as constants.
 *
 * A percentage assembled at render time is invisible to any check that
 * only reads stored strings, which is why the real gate drives every
 * exported composer and why this fixture ships one.
 */
export function masteryLine(percent: number): string {
  return `You are ${percent}% mastered on this path.`;
}
