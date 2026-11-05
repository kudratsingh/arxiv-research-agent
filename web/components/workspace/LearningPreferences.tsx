import { useState, type FormEvent } from "react";
import { contextRequest, errorMessage, type ContextIndex, type ContextPreferences } from "@/lib/workspace/api";
import { invalidateContextIndex, useContextIndex } from "@/lib/workspace/useContextIndex";
import { useManualForm } from "@/lib/workspace/useManualForm";
import { Message } from "./Common";
export default function LearningPreferences({ onSaved }: { onSaved: () => void }) {
  const { index, error, reload, setIndex } = useContextIndex();
  const [notice, setNotice] = useState("");
  if (!index) return <div>{error ? <p role="alert">{error}<button type="button" onClick={() => void reload()}>Retry learning preferences</button></p> : <p aria-busy="true">Loading your declared learning preferences…</p>}</div>;
  return <><PreferencesForm key={index.preferences.revision} index={index} onReload={() => void reload()} onSaved={value => { setIndex({ ...index, preferences: value }); setNotice(`Learning preferences saved on the server at revision ${value.revision}. Your legacy interests and organizing question are unchanged.`); onSaved(); }} /><Message>{notice}</Message></>;
}
function PreferencesForm({ index, onSaved, onReload }: { index: ContextIndex; onSaved: (value: ContextPreferences) => void; onReload: () => void }) {
  const form = useManualForm(index.principal_key_id, "learning-preferences", "preferences", index.preferences.revision, {
    mode: index.preferences.data.default_mode, background: index.preferences.data.learning_background, goals: index.preferences.data.learning_goals.join("\n"),
  });
  async function save(event: FormEvent) {
    event.preventDefault(); if (form.busy) return;
    const input = { revision: form.draft.revision, data: { default_mode: form.values.mode === "research" ? "research" : "learn", learning_background: form.values.background, learning_goals: form.values.goals!.split("\n").map(text => text.trim()).filter(Boolean) } };
    const request_id = form.attempt(input); form.setBusy(true);
    try { const value = await contextRequest<ContextPreferences>("/preferences", { ...input, request_id }); form.clear(); invalidateContextIndex(); onSaved(value); }
    catch (failure) { form.setNotice(errorMessage(failure)); } finally { form.setBusy(false); }
  }
  return <form id={form.surfaceId} className="workspace-controls" aria-label="Learning preferences" onSubmit={event => void save(event)}>
    <p className="daily-muted">Optional declarations for reference while learning. These do not currently add ranking terms or generate teaching. They have a separate revision from interests and your saved organizing question; reading never establishes mastery.</p>
    {index.preferences.revision > form.draft.revision && <section className="workspace-version-notice" aria-label="Latest saved learning preferences for review"><h3>Review the latest saved revision</h3><p>{index.preferences.data.default_mode}</p><p>{index.preferences.data.learning_background}</p><ul>{index.preferences.data.learning_goals.map((goal, i) => <li key={i}>{goal}</li>)}</ul><button type="button" disabled={form.busy} onClick={() => form.rebase(index.preferences.revision)}>Keep my edits on reviewed revision</button></section>}
    <label>Default workspace mode<select value={form.values.mode} disabled={form.busy} onChange={event => form.change("mode", event.target.value)}><option value="learn">Explore &amp; Learn</option><option value="research">Research</option></select></label>
    <label>Declared background (optional)<textarea maxLength={3000} rows={4} value={form.values.background} readOnly={form.busy} onChange={event => form.change("background", event.target.value)} /></label>
    <label>Learning goals, one per line (optional)<textarea maxLength={15000} rows={4} value={form.values.goals} readOnly={form.busy} onChange={event => form.change("goals", event.target.value)} /></label>
    <p>Saved preferences revision {index.preferences.revision} · local edit base {form.draft.revision}</p>
    <div className="workspace-toolbar"><button className="daily-button" disabled={form.busy}>{form.busy ? "Saving learning preferences…" : "Save learning preferences"}</button><button type="button" className="daily-secondary" disabled={form.busy} onClick={() => form.clear(true)}>Discard local learning edits</button><button type="button" disabled={form.busy} onClick={onReload}>Reload saved learning preferences</button></div>
    {!form.storage && <p className="workspace-version-notice">Browser recovery is unavailable. Copy edits before a full reload.</p>}<Message>{form.notice}</Message>
  </form>;
}
