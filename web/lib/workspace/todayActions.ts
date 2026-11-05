import { requestId, workspaceRequest, type ProfileData, type WorkspaceState } from "./api";

/** Loaded only for an explicit preference/check action, never while reading. */
export async function saveTodayProfile(state: WorkspaceState, patch: Partial<Pick<ProfileData, "minutes" | "pinned_entry_id">>, pending: Map<string, string>, edition = false) {
  const input = { revision: state.profile.revision, data: { ...state.profile.data, ...patch } };
  const fingerprint = JSON.stringify(input), id = pending.get(fingerprint) ?? requestId();
  pending.set(fingerprint, id);
  await workspaceRequest("profile", { ...input, request_id: id });
  if (edition) await workspaceRequest("edition", {});
}
export async function checkTodaySources() { await workspaceRequest("refresh", { source_ids: [] }); }
