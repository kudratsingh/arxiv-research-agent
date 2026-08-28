/**
 * WO-14's additions to the copy dictionary, held to WO-12's gate.
 *
 * `web/tests/copy/forbidden.test.ts` already walks every exported value of
 * `lib/copy/threads.ts`, so the three strings this work order added are
 * inside that gate the moment they are exported. What that file cannot see
 * — by design, because it walks the DICTIONARY — is:
 *
 *   1. the one string the rail COMPOSES outside the dictionary
 *      (`threadMenuLabel`, which joins a dictionary word to the user's own
 *      thread title, the same shape `deleteDialog()` uses), and
 *   2. whether the new strings say the thing 03 asks them to say, as
 *      opposed to merely avoiding the words it forbids.
 *
 * Both are here, driven through the SAME lists — `DENY_LIST`,
 * `LEXICON_PHRASES`, `findForbidden` — rather than through a second copy of
 * them, so this file cannot drift from the gate it extends.
 */

import { describe, expect, it } from "vitest";

import { threadMenuLabel, threadRowHref } from "@/components/patterns/ThreadList";
import {
  DENY_LIST,
  LEXICON_PHRASES,
  findForbidden,
  type ForbiddenPhrase,
} from "@/lib/copy";
import { THREAD_RAIL, THREAD_ROW, deleteDialog } from "@/lib/copy/threads";

/** Everything WO-14 added to the dictionary, plus the composed forms. */
const ADDED: Array<{ path: string; value: string }> = [
  { path: "THREAD_RAIL.deleteFailed", value: THREAD_RAIL.deleteFailed },
  { path: "THREAD_ROW.live", value: THREAD_ROW.live },
  { path: "deleteDialog().close", value: deleteDialog("A thread").close },
  // The composed label, driven with the shapes a real title takes: the
  // user's own words, an empty title, and one with a quotation mark in it.
  { path: "threadMenuLabel(title)", value: threadMenuLabel("Sparse attention survey") },
  { path: "threadMenuLabel(empty)", value: threadMenuLabel("") },
  { path: "threadMenuLabel(padded)", value: threadMenuLabel("   ") },
  { path: "threadMenuLabel(quoted)", value: threadMenuLabel('The "reader" node') },
];

describe("the additions face the same deny-list as the dictionary", () => {
  it.each(DENY_LIST as ForbiddenPhrase[])("nothing says $id", (phrase) => {
    const offenders = ADDED.filter((entry) => phrase.pattern.test(entry.value));
    expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
  });

  it.each(LEXICON_PHRASES as ForbiddenPhrase[])(
    "no added string says $id",
    (phrase) => {
      // The user's own title is exempt from the lexicon for the same reason
      // `deleteDialog()`'s is: it is the user's words, not the product's.
      // Only OUR half of each composed string is checked.
      const ours = ADDED.filter((entry) => !entry.path.startsWith("threadMenuLabel"));
      const offenders = ours.filter((entry) => phrase.pattern.test(entry.value));
      expect(offenders, `${phrase.id}: ${phrase.why}`).toEqual([]);
    },
  );

  it("keeps the product's half of the composed label clean whatever the title is", () => {
    // The title passes through unedited — including a banned noun, because
    // editing the user's own question is the lossiness RC-16 forbids — so
    // the assertion is over the prefix the dictionary owns.
    expect(threadMenuLabel("The node that failed")).toBe(
      `${THREAD_ROW.menuLabel}: The node that failed`,
    );
    expect(findForbidden(THREAD_ROW.menuLabel, DENY_LIST)).toEqual([]);
    expect(findForbidden(THREAD_ROW.menuLabel, LEXICON_PHRASES)).toEqual([]);
  });
});

describe("the additions say what 03 asks them to say", () => {
  it("marks the attached run with one word (03 §2.1, §3.4)", () => {
    expect(THREAD_ROW.live).toBe("Live");
    // A mark alone would be colour-only; the word is what survives forced
    // colours and a monochrome display.
    expect(THREAD_ROW.live.trim()).not.toBe("");
  });

  it("reports a failed deletion without offering to repeat it (R-01, H6)", () => {
    expect(THREAD_RAIL.deleteFailed).toBe(
      "That thread was not deleted. It is back in the list.",
    );
    // No imperative to try again, anywhere in the sentence.
    expect(THREAD_RAIL.deleteFailed).not.toMatch(/try again|retry|resend/i);
    // And it describes the list the user is looking at, which is what
    // WO-11's rollback actually restored.
    expect(THREAD_RAIL.deleteFailed).toMatch(/back in the list/);
  });

  it("names the close mark something other than Cancel", () => {
    const copy = deleteDialog("A thread");
    expect(copy.close).toBe("Close without deleting");
    expect(copy.close).not.toBe(copy.cancel);
  });

  it("keeps the rail's own recovery sentence about a read, not a write", () => {
    expect(THREAD_RAIL.errorRecovery).toBe(
      "Retry loading the list. Nothing is sent again on its own.",
    );
  });
});

describe("the URL rule is copy-adjacent, so it is gated here too", () => {
  it("never invents a parameter the route did not have", () => {
    expect(threadRowHref("thread-1", "thread-1", null)).toBe("/c/thread-1");
    expect(threadRowHref("thread-1", "thread-1", "")).toBe("/c/thread-1");
    expect(threadRowHref("thread-1", null, "job-1")).toBe("/c/thread-1");
  });
});
