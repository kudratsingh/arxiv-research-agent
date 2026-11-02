"use client";
import { useState } from "react";
import { parsePreview, PREVIEW_KEY, type PreviewData } from "@/lib/daily/store";
import {
  errorMessage,
  workspaceRequest,
  WorkspaceError,
  type ImportPreview,
} from "@/lib/workspace/api";

export function PreviewImport({
  revision,
  reload,
  announce,
}: {
  revision: number;
  reload: () => Promise<void>;
  announce: (value: string) => void;
}) {
  const [record, setRecord] = useState<PreviewData | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [importProfile, setImportProfile] = useState(false);
  const [busy, setBusy] = useState(false);
  const [baseRevision, setBaseRevision] = useState(revision);
  const [original, setOriginal] = useState("");
  const [pasted, setPasted] = useState("");
  async function inspect(rawInput?: string) {
    setBusy(true);
    setPreview(null);
    try {
      const raw = rawInput ?? window.localStorage.getItem(PREVIEW_KEY);
      if (!raw) {
        announce(
          "There is no fictional-preview record in this browser. Nothing was imported.",
        );
        return;
      }
      const parsed = parsePreview(raw);
      setOriginal(raw);
      setRecord(parsed);
      setBaseRevision(revision);
      setPreview(
        await workspaceRequest<ImportPreview>("import/preview", {
          record: parsed,
          profile_revision: revision,
          import_profile: importProfile,
        }),
      );
      announce(
        "Import preview ready. Review conflicts before applying; your browser original is retained.",
      );
    } catch (error) {
      announce(
        error instanceof WorkspaceError
          ? errorMessage(error)
          : "This preview record is malformed, too large or uses an unsupported schema. The original was not changed.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function apply() {
    if (!preview || !record || preview.conflicts.length) return;
    setBusy(true);
    try {
      const result = await workspaceRequest<ImportPreview>("import/apply", {
        record,
        profile_revision: baseRevision,
        import_profile: importProfile,
        digest: preview.digest,
      });
      setPreview(result);
      await reload();
      announce(
        "Import saved on the server. Your browser original has not been deleted. Repeating this import will not duplicate notes.",
      );
    } catch (error) {
      announce(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="workspace-import" aria-labelledby="import-title">
      <span className="daily-eyebrow">Explicit one-time transfer</span>
      <h2 id="import-title">Bring your preview notes with you.</h2>
      <p className="daily-muted">
        Preview sources remain labelled fictional. Import keeps authored notes
        against those preview sources; it does not attach them to real papers.
        Server edits are never silently overwritten.
      </p>
      <label className="workspace-check-label">
        <input
          type="checkbox"
          checked={importProfile}
          onChange={(event) => {
            setImportProfile(event.target.checked);
            setPreview(null);
          }}
        />
        Also import the preview interests and research question
      </label>
      <button
        className="daily-secondary"
        disabled={busy}
        onClick={() => void inspect()}
      >
        Preview browser import
      </button>
      <details className="workspace-import-file">
        <summary className="daily-link">
          Import an export from a different preview address
        </summary>
        <p className="daily-muted">
          Browser storage belongs to its address. If the preview used another
          port, download its JSON export there, then choose or paste that file
          here. Previewing never applies it.
        </p>
        <label>
          Preview JSON file
          <input
            type="file"
            accept="application/json,.json"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              if (file.size > 200000) {
                announce(
                  "Preview files are limited to 200 KB. Nothing was imported.",
                );
                return;
              }
              void file
                .text()
                .then((raw) => {
                  setPasted(raw);
                  setPreview(null);
                  announce(
                    "File loaded for review. Choose Preview exported JSON to inspect it before applying.",
                  );
                })
                .catch(() =>
                  announce(
                    "The file could not be read. Your original is unchanged.",
                  ),
                );
            }}
          />
        </label>
        <label>
          Or paste exported preview JSON
          <textarea
            rows={4}
            maxLength={200000}
            value={pasted}
            onChange={(event) => {
              setPasted(event.target.value);
              setPreview(null);
            }}
          />
        </label>
        <button
          className="daily-secondary"
          disabled={busy || !pasted.trim()}
          onClick={() => void inspect(pasted)}
        >
          Preview exported JSON
        </button>
      </details>
      {preview && (
        <div className="workspace-alert">
          <h3>Review this transfer</h3>
          <ul>
            <li>{preview.entries_new} new notes/questions/actions</li>
            <li>{preview.entries_existing} already imported</li>
            <li>
              {preview.profile_will_change
                ? "Profile will change after confirmation"
                : "Your server profile stays as it is"}
            </li>
            <li>Browser original retained</li>
          </ul>
          {preview.conflicts.length > 0 ? (
            <>
              <strong>Resolve these conflicts before importing:</strong>
              <ul>
                {preview.conflicts.map((conflict) => (
                  <li key={conflict}>{conflict}</li>
                ))}
              </ul>
              <p>
                Export the preview below and reconcile the notes manually; no
                conflicting server edit has been replaced.
              </p>
            </>
          ) : (
            <button
              className="daily-button"
              disabled={busy}
              onClick={() => void apply()}
            >
              Confirm import
            </button>
          )}
          {original && (
            <p>
              <a
                className="daily-link"
                href={`data:application/json;charset=utf-8,${encodeURIComponent(original)}`}
                download="research-preview-original.json"
              >
                Export supplied original
              </a>
            </p>
          )}
        </div>
      )}
    </section>
  );
}
