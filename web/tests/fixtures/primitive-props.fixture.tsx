/**
 * POSITIVE fixture for the primitives/no-data-layer ESLint rule (WO-07
 * criterion 1).
 *
 * The same component with the data hoisted into props. It MUST lint clean,
 * which is what shows the rule rejects the *reach* into the data layer
 * rather than rejecting a component that displays server data at all —
 * every state below is reachable by passing props, which is the whole of
 * 04-ARCHITECTURE.md §5.1's layer rule.
 */

import { StatusBadge } from "@/components/primitives/StatusBadge";
import type { StatusSeverity } from "@/lib/tokens";

export function PrimitivePropsFixture({
  severity,
  word,
}: {
  severity: StatusSeverity;
  word: string;
}) {
  return <StatusBadge severity={severity}>{word}</StatusBadge>;
}
