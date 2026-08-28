// M0 compatibility shim (05-MIGRATION.md §1.1).
//
// These types are no longer hand-written. They are now aliases into
// the generated OpenAPI types (`lib/api/models.ts`) plus the
// hand-written SSE overlay (`lib/api/events.ts`), so a backend schema
// change is a compile error here instead of a runtime surprise.
//
// This file keeps the `@/lib/types` specifier working for existing
// components. New code should import from `@/lib/api/index`.
//
// Deleted in M4 (WO-31), once the last consumer has moved.

export * from "./api/models";
export * from "./api/events";
