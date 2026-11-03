"use client";

/** Display the frozen server receipt; never infer an allocation from a percentage. */
export function AllocationReceipt({
  allocation,
  minutes,
  compact = false,
}: {
  allocation: Record<string, unknown> | undefined;
  minutes?: number;
  compact?: boolean;
}) {
  const values = allocation ?? {};
  const numeric = [
    "slots",
    "requested_fraction",
    "planned_max_exploration_slots",
    "max_exploration_slots",
    "actual_exploration_slots",
    "actual_items",
    "unused_slots",
  ];
  if (
    !numeric.every(
      (field) =>
        typeof values[field] === "number" && Number.isFinite(values[field]),
    ) ||
    (values.actual_fraction !== null &&
      typeof values.actual_fraction !== "number")
  ) {
    return (
      <p className="daily-muted">
        This earlier edition has no recorded exploration allocation. Its choices
        have not been recalculated against today’s candidates.
      </p>
    );
  }
  const count = (field: string) => values[field] as number;
  const requested = `${Number((count("requested_fraction") * 100).toFixed(1))}%`;
  const actual =
    values.actual_fraction === null
      ? "no items"
      : `${Number(((values.actual_fraction as number) * 100).toFixed(1))}%`;
  return (
    <div
      className={`workspace-allocation${compact ? " workspace-allocation-compact" : ""}`}
    >
      <p>
        <strong>
          {minutes ? `${minutes} min · ` : ""}
          {count("actual_exploration_slots")} exploration{" "}
          {count("actual_exploration_slots") === 1 ? "item" : "items"}
        </strong>{" "}
        among {count("actual_items")} selected ({actual}). Requested cap:{" "}
        {requested}.
      </p>
      {compact ? (
        <p className="daily-muted">
          {count("unused_slots")} of {count("slots")} reading slots unused.
          Allocation uses the actual candidate set.
        </p>
      ) : (
        <details>
          <summary className="daily-link">
            Inspect this edition’s allocation
          </summary>
          <dl className="workspace-allocation-details">
            <dt>Reading slots</dt>
            <dd>{count("slots")} at five minutes per item</dd>
            <dt>Maximum before candidate limits</dt>
            <dd>{count("planned_max_exploration_slots")}</dd>
            <dt>Maximum for the final item count</dt>
            <dd>{count("max_exploration_slots")}</dd>
            <dt>Unused slots</dt>
            <dd>{count("unused_slots")}</dd>
            <dt>Rounding</dt>
            <dd>Down against the final count; the cap is never rounded up.</dd>
          </dl>
        </details>
      )}
    </div>
  );
}
