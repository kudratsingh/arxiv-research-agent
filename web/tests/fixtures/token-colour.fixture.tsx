/**
 * POSITIVE fixture for the tokens/no-literal-colour ESLint rule.
 *
 * The same component expressed in tokens. It MUST lint clean, which is
 * what shows the rule rejects literals rather than rejecting colour
 * styling in general (WO-01 acceptance criterion 1).
 */

import { color, elevation } from "@/lib/tokens";

export function TokenColourFixture() {
  return (
    <div
      className="border border-border-subtle bg-canvas text-ink shadow-elev-1"
      style={{ outlineColor: color.focus, boxShadow: elevation["elev-2"] }}
    >
      This component styles itself with tokens.
    </div>
  );
}
