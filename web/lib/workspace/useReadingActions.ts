"use client";
import { useRef, useState } from "react";
import {
  errorMessage,
  requestId,
  workspaceRequest,
  type ReadingData,
  type ReadingRevision,
  type WorkItem,
  type WorkspaceState,
} from "./api";

export function useReadingActions(
  state: WorkspaceState | null,
  setState: (state: WorkspaceState) => void,
  announce: (text: string) => void,
) {
  const [busy, setBusy] = useState(false);
  const [undo, setUndo] = useState<{
    work: WorkItem;
    data: ReadingData;
  } | null>(null);
  const attempts = useRef(new Map<string, string>());
  async function write(item: WorkItem, data: ReadingData, reversible = true) {
    if (!state || busy) return false;
    const input = {
      work_id: item.work_id,
      revision: item.reading.revision,
      data,
    };
    const fingerprint = JSON.stringify(input);
    const id = attempts.current.get(fingerprint) ?? requestId();
    attempts.current.set(fingerprint, id);
    setBusy(true);
    try {
      const reading = await workspaceRequest<ReadingRevision>("reading", {
        ...input,
        request_id: id,
      });
      setState({
        ...state,
        works: state.works.map((work) =>
          work.work_id === item.work_id ? { ...work, reading } : work,
        ),
      });
      if (reversible)
        setUndo({
          work: { ...item, reading },
          data: {
            status: item.reading.status,
            anchor: item.reading.anchor,
            version_id: item.reading.version_id,
            snoozed_until: item.reading.snoozed_until,
          },
        });
      else setUndo(null);
      announce(`Saved on the server: ${data.status.replaceAll("_", " ")}.`);
      return true;
    } catch (error) {
      announce(errorMessage(error));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return {
    busy,
    hasUndo: undo !== null,
    undoWorkId: undo?.work.work_id ?? null,
    undo: async () => undo ? write(undo.work, undo.data, false) : false,
    write,
    status: (item: WorkItem, status: ReadingData["status"]) =>
      write(item, {
        status,
        anchor: item.reading.anchor,
        version_id: item.reading.version_id || item.version_id,
        snoozed_until:
          status === "snoozed"
            ? new Date(Date.now() + 86_400_000).toISOString()
            : null,
      }),
  };
}
