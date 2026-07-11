// Minimal client for the arxiv-research-agent HTTP API.
//
// Flow:
//   1. POST /research with the query -> get {job_id, status_url, stream_url}
//   2. Open EventSource on stream_url; each frame appends to the event log
//   3. On terminal event (job_completed / job_failed / job_cancelled),
//      GET status_url to fetch the final result + metrics
//
// Vanilla JS on purpose (ADR 0029) — no build step, no framework runtime.

const submitBtn = document.getElementById("submit");
const queryInput = document.getElementById("query");
const jobMeta = document.getElementById("job-meta");
const progressPanel = document.getElementById("progress-panel");
const eventLog = document.getElementById("event-log");
const summary = document.getElementById("summary");
const reportPanel = document.getElementById("report-panel");
const reportEl = document.getElementById("report");

const stat = {
  iterations: document.getElementById("stat-iterations"),
  quality: document.getElementById("stat-quality"),
  cost: document.getElementById("stat-cost"),
  calls: document.getElementById("stat-calls"),
  elapsed: document.getElementById("stat-elapsed"),
};

let activeSource = null;

submitBtn.addEventListener("click", async () => {
  const query = queryInput.value.trim();
  if (!query) {
    queryInput.focus();
    return;
  }
  await startResearch(query);
});

queryInput.addEventListener("keydown", (e) => {
  // Cmd/Ctrl + Enter submits — a modest ergonomic touch.
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    submitBtn.click();
  }
});

async function startResearch(query) {
  resetUi();
  setBusy(true);

  let submission;
  try {
    const resp = await fetch("/research", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!resp.ok) {
      throw new Error(`POST /research failed (${resp.status})`);
    }
    submission = await resp.json();
  } catch (err) {
    appendEvent("error", `submit failed: ${err.message}`);
    setBusy(false);
    return;
  }

  jobMeta.textContent = `job ${submission.job_id}`;
  progressPanel.hidden = false;
  appendEvent("job_submitted", `job_id=${submission.job_id}`);

  openStream(submission.job_id, submission.stream_url, submission.status_url);
}

function openStream(jobId, streamUrl, statusUrl) {
  // Close any prior stream defensively; the UI never keeps two open,
  // but restarting via a resubmit could race the cleanup otherwise.
  if (activeSource) {
    activeSource.close();
    activeSource = null;
  }

  const source = new EventSource(streamUrl);
  activeSource = source;

  const terminalEvents = new Set([
    "job_completed",
    "job_failed",
    "job_cancelled",
  ]);

  const listen = (name) => {
    source.addEventListener(name, (evt) => {
      let payload = null;
      try {
        payload = JSON.parse(evt.data);
      } catch (_) {}
      renderEvent(name, payload);
      if (terminalEvents.has(name)) {
        source.close();
        activeSource = null;
        setBusy(false);
        finalize(jobId, statusUrl, name, payload);
      }
    });
  };

  ["job_started", "node_completed", ...terminalEvents].forEach(listen);

  source.addEventListener("error", (evt) => {
    // EventSource auto-reconnects unless we close it. On a terminal
    // job we're already closed. On network hiccups mid-run, browser
    // will retry; surface a subtle note so the user isn't surprised.
    if (source.readyState === EventSource.CLOSED) return;
    appendEvent("stream_note", "connection interrupted; browser is retrying");
  });
}

async function finalize(jobId, statusUrl, terminalName, terminalPayload) {
  // GET the status URL to pick up the full report body — the stream
  // only carries scalar metrics + a terminal frame, not the report
  // markdown (ADR 0026 keeps SSE frames compact).
  let detail;
  try {
    const resp = await fetch(statusUrl);
    if (!resp.ok) throw new Error(`GET status failed (${resp.status})`);
    detail = await resp.json();
  } catch (err) {
    appendEvent("error", `fetch result failed: ${err.message}`);
    return;
  }

  updateSummary(detail);
  summary.hidden = false;

  if (detail.result) {
    reportPanel.hidden = false;
    reportEl.textContent = detail.result;
  }

  if (terminalName === "job_failed" && detail.error) {
    reportPanel.hidden = false;
    reportEl.textContent = `FAILED (${detail.error_type || "unknown"})\n\n${detail.error}`;
  }
}

function renderEvent(name, payload) {
  if (name === "job_started") {
    appendEvent(name, "workflow starting");
    return;
  }
  if (name === "node_completed" && payload) {
    const parts = [`node=${payload.node}`];
    if (payload.state_delta) {
      for (const [k, v] of Object.entries(payload.state_delta)) {
        parts.push(`${k}=${formatValue(v)}`);
      }
    }
    appendEvent(name, parts.join(" "));
    return;
  }
  if (name === "job_completed" && payload) {
    appendEvent(name, `elapsed=${payload.elapsed_sec ?? "?"}s`);
    return;
  }
  if (name === "job_failed" && payload) {
    appendEvent(name, `${payload.error_type || "error"}: ${payload.error || ""}`);
    return;
  }
  if (name === "job_cancelled") {
    appendEvent(name, "cancelled");
    return;
  }
  appendEvent(name, "");
}

function updateSummary(detail) {
  stat.iterations.textContent = fmt(detail.iterations);
  stat.quality.textContent = fmtScore(detail.quality_score);
  stat.cost.textContent = fmtCost(detail.cost_usd);
  stat.calls.textContent = fmt(detail.llm_calls);
  stat.elapsed.textContent = detail.elapsed_sec != null
    ? `${detail.elapsed_sec.toFixed(1)}s`
    : "-";
}

function fmt(v) { return v == null ? "-" : String(v); }
function fmtScore(v) { return v == null ? "-" : v.toFixed(2); }
function fmtCost(v) { return v == null ? "-" : `$${v.toFixed(4)}`; }

function formatValue(v) {
  if (typeof v === "number" && !Number.isInteger(v)) return v.toFixed(2);
  return String(v);
}

function appendEvent(name, detail) {
  const li = document.createElement("li");
  const time = new Date().toLocaleTimeString([], { hour12: false });
  li.className = `event event-${name}`;
  li.innerHTML =
    `<span class="event-time">${time}</span>` +
    `<span class="event-name">${escapeHtml(name)}</span>` +
    `<span class="event-detail">${escapeHtml(detail)}</span>`;
  eventLog.appendChild(li);
  eventLog.scrollTop = eventLog.scrollHeight;
}

function resetUi() {
  eventLog.innerHTML = "";
  reportEl.textContent = "";
  reportPanel.hidden = true;
  summary.hidden = true;
  jobMeta.textContent = "";
}

function setBusy(busy) {
  submitBtn.disabled = busy;
  submitBtn.textContent = busy ? "Running…" : "Run research";
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
