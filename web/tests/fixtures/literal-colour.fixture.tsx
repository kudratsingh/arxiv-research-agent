/**
 * NEGATIVE fixture for the tokens/no-literal-colour ESLint rule.
 *
 * This file MUST fail `eslint`. web/tests/tokens.test.ts lints it and
 * asserts one no-restricted-syntax error per literal below, which is
 * what proves the rule actually fires rather than merely being
 * configured (WO-01 acceptance criterion 1).
 *
 * It is never imported by application code, and `npm run lint` walks
 * only app/ components/ lib/, so the repository lint stays green.
 * Do not "fix" the colours below.
 */

const SIX_DIGIT_HEX = "#275DAD";
const THREE_DIGIT_HEX = "#fff";
const FUNCTIONAL_RGB = "rgba(23, 43, 49, 0.06)";
const FUNCTIONAL_HSL = "hsl(186 70% 29%)";
const INTERPOLATED = `border-color: #D2DFE2; box-shadow: 0 1px 2px ${FUNCTIONAL_RGB}`;

export function LiteralColourFixture() {
  return (
    <div
      className="bg-[#F3F7F8]"
      style={{ color: SIX_DIGIT_HEX, borderColor: THREE_DIGIT_HEX }}
      data-shadow={FUNCTIONAL_HSL}
      data-inline={INTERPOLATED}
    >
      This component styles itself with literal colours instead of tokens.
    </div>
  );
}
