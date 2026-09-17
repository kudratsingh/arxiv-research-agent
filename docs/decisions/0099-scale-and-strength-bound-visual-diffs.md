# 0099. Visual diffs bound both changed area and pixel strength

- **Status**: accepted
- **Date**: 2026-09-17
- **Deciders**: assurance lane (S10)

## Context

The visual suite used one allowance for every screenshot:
`maxDiffPixels: 200`. A 412 × 915 phone capture and a 1440 × 900 desktop
capture therefore had the same budget despite a 3.4× difference in area. The
budget also relied on Playwright's default per-pixel threshold of `0.2`, so a
low-contrast change could disappear before the 200-pixel area limit was
applied.

The 2026-09-17 golden pass measured both failure modes. Changing the spine
label from `Report` to `Briefing` at 412 px changed about 270 raw pixels, but
the comparator counted fewer than 200 after applying its default threshold.
Sixteen of the 26 stale snapshots therefore stayed green. The
`rail-error-upstream-{light,dark}-412` snapshots had not been regenerated
since PR 118 and also stayed green because the changed background sat behind
a dim scrim.

The old tolerance had sound evidence behind it: 45 of 48 goldens were
byte-identical across forced regenerations, and the other three differed by
4, 9 and 14 raw pixels because a sticky rail can land at a fractional
compositor offset. The defect was the shape of the allowance, not the need
for one.

## Decision

Every visual assertion uses both of Playwright's relevant controls:

- `maxDiffPixelRatio: 0.00024` scales the changed-area budget with the image;
- `threshold: 0.1` makes lower-contrast YIQ differences count.

The ratio permits about 90 pixels in a 412 × 915 capture and 311 in a
1440 × 900 capture. At the stricter threshold the known desktop sticky-rail
compositor seam measures 281 pixels, so the desktop budget still admits the
measured rendering noise while the phone budget falls below half of the old
flat allowance.

The two controls answer different questions. The threshold decides whether a
pixel's perceived colour difference is strong enough to count. The ratio
then bounds how much of the surface may differ. Setting both keeps a
low-contrast change behind a scrim visible to the comparison and keeps the
allowed area proportional to the capture.

## Proof

Two temporary source changes were built into the isolated S10 Compose stack;
neither change nor any resulting image was retained.

1. Reverting the spine label from `Briefing` to `Report` made 12 of the 24
   412 px visual cases fail in both themes. Each affected image counted
   195–203 differing pixels against the 90-pixel phone budget.
2. Translating the page two pixels made both
   `rail-error-upstream-{light,dark}-412` cases fail. The comparator counted
   12,589 pixels in light mode and 11,256 in dark mode, including the
   scrim-dimmed surface.

After restoring both mutations, the complete 55-test visual suite passed
twice against the current goldens. No golden image moved.

## Consequences

- A one-word spine change at phone width is now larger than the phone budget,
  even when only part of the glyph edge crosses the per-pixel threshold.
- Low-contrast changes behind overlays reach the area comparison instead of
  being discarded at Playwright's default threshold.
- Larger captures receive a proportionally larger allowance, preserving the
  measured 281-pixel desktop compositor seam without granting that allowance
  to phone captures.
- The constants and their measurement remain beside the visual inventory, and
  the e2e README publishes the same numbers for future remeasurement.
- This remains a comparator for rendered output, so engine upgrades and
  intentional visual changes still require inspection before a golden is
  regenerated.

## Alternatives considered

- **Lower the flat pixel count.** Rejected: a bound low enough to catch the
  phone label would reject the measured 281-pixel desktop compositor seam.
- **Use a ratio with Playwright's default threshold.** Rejected: scaling the
  area budget does not help pixels behind the scrim if the strength filter
  discards them first.
- **Lower only the threshold.** Rejected: it exposes the low-contrast pixels
  but leaves the same mismatched area allowance across phone and desktop
  captures.
- **Regenerate the stale goldens.** Rejected: that would bless the
  comparator's false negatives without making the next small copy or
  scrim-dimmed change detectable.
