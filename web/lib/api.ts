// M0 compatibility shim (05-MIGRATION.md §1.1).
//
// The implementation moved to `web/lib/api/`. This file keeps the
// `@/lib/api` specifier working with unchanged names and signatures so
// existing components and the 78 existing tests need no edit — that is
// the evidence M0 is behaviour-neutral. New code should import from
// `@/lib/api/index` directly.
//
// Deleted in M4 (WO-31), once the last consumer has moved.
//
// The specifier below must stay `./api/index`. Writing `./api` would
// resolve back to this file.

export * from "./api/index";
