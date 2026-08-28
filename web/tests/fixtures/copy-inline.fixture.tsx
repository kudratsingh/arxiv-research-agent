/**
 * WO-12 criterion 1 — the fixture that MUST fail lint.
 *
 * It is committed, it is real TSX, and `web/tests/copy/lint.test.ts` runs
 * ESLint over it and asserts the exact violation count. That is the
 * difference between a rule that is configured and a rule that fires.
 *
 * It lives here rather than in components/patterns/ for the reason WO-01's
 * and WO-07's fixtures do: `npm run lint` walks only app/, components/ and
 * lib/, so a file that is supposed to fail never turns the repository lint
 * red — while `copy/no-inline-text`'s `files` list reaches it anyway.
 *
 * Nine violations across the seven shapes the rule claims to cover. It
 * carries NO literal colour, deliberately: WO-01's repository-wide scan
 * (web/tests/tokens.test.ts) reads every .tsx under web/ and has a
 * hard-coded exemption list, so a hex here would fail that test instead of
 * this one. The proof that this block did not switch WO-01's
 * no-literal-colour rule off is in web/tests/copy/lint.test.ts, which lints
 * a synthetic patterns file through `ESLint.lintText` and reads the
 * resolved config back.
 *
 * The strings a passing pattern is allowed to keep live in
 * copy-dictionary.fixture.tsx.
 */

export function InlineTextFixture({ failed }: { failed: boolean }) {
  const node = "reader";
  return (
    <div className="text-critical" data-state={failed ? "failed" : "ok"}>
      The run failed.
      <p>{"It stopped after the last observed checkpoint."}</p>
      <p>{`It stopped after ${node}.`}</p>
      <p>{failed ? "Failed" : "Complete"}</p>
      <p>{failed && "Ask again to start a new run."}</p>
      <p>{"Cost" + " and quality"}</p>
      <>{"A fragment child is still a child slot."}</>
      <span aria-label="this one is out of scope" data-note="so is this" />
    </div>
  );
}
