// The one number the ring, the redactor and the surface all need.
//
// A THREE-LINE MODULE WITH A REASON. `components/patterns/Diagnostics.tsx`
// needs the capacity to render the retained line, and importing it from
// `./ring` would pull the buffer — a class with a dozen methods and a
// module-scope instance — into the Storybook project's module graph, where
// no story ever pushes to it. vitest.config.mts records what that does:
// a module loaded by BOTH vitest projects has its function list
// CONCATENATED in the merged report, so an unexercised class arrives as a
// doubled denominator with an unmoved numerator. A constants module has no
// functions and therefore no denominator to double.
//
// It is also the honest factoring. The capacity is a fact from
// 04-ARCHITECTURE.md §9.2, not a property of the data structure that
// happens to enforce it.

/** 04 §9.2: "The last 200 lifecycle records". Exactly 200, not "about". */
export const RING_CAPACITY = 200;
