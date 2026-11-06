"""Explicit, retry-safe examples on the isolated modes-preview only; no source fetch.

Run from worktree root with the locked Python using stdin. Read the existing
local API credential without printing it. Never targets owner3137 or its API.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

import src
from src.workspace.context_schemas import LearningThreadData

assert Path(src.__file__).resolve().is_relative_to(Path.cwd())

BASE = "http://127.0.0.1:8178/workspace"
OUT = Path("outputs/modes-d0")
KEY = (OUT / ".workspace-api-key").read_text().strip()
assert os.environ.get("ANTHROPIC_API_KEY") == "local-preview-disabled"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Local example seeding refuses redirects before dispatch")


LOCAL_HTTP = build_opener(NoRedirect)


def call(path, data=None):
    assert path.startswith("/") and not path.startswith("//")
    request = Request(
        BASE + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={"X-API-Key": KEY, "Content-Type": "application/json"},
    )
    with LOCAL_HTTP.open(request, timeout=20) as response:
        assert response.geturl() == BASE + path, "Redirects are not part of this seed"
        return json.load(response)


def identity(kind, name):
    return (
        kind
        + "-"
        + hashlib.sha256(("modes-owner-walkthrough-v1:" + name).encode()).hexdigest()[:32]
    )


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


state = call("/context/state?mode=learn")
assert state["principal_key_id"] == "modes-preview", "Never seed another principal"
assert not state["schedule"]["enabled"]
before_profile = digest(state["profile"])
before_sources = digest(state["sources"])
index = call("/context")
examples = [
    (
        "Tool use with checkpoints",
        "arxiv:2210.03629",
        "When should a research agent pause before using a tool?",
        "Reasoning and acting",
        "Understand how reasoning and action interact, and note where a human checkpoint could help.",
    ),
    (
        "Ground a research answer",
        "arxiv:2310.11511",
        "Which parts of a research answer can be checked against retained sources?",
        "Retrieval and reflection",
        "Understand the difference between retrieving a source and supporting a claim.",
    ),
    (
        "Keep learning while adapting",
        "arxiv:2610.40740",
        "How can held-out anchors check behavioral retention during continual adaptation?",
        "Held-out anchors",
        "Learn what a held-out anchor measures and what it leaves untested.",
    ),
]
receipts = []
for name, work_id, question, prerequisite, goal in examples:
    work = next(w for w in state["works"] if w["work_id"] == work_id)
    version = next(v for v in work["versions"] if v["version_id"] == work["version_id"])
    reference = {
        "work_id": work_id,
        "version_id": version["version_id"],
        "version_hash": version["content_hash"],
        "anchor": "abstract:0:180",
        "source_scope": "abstract",
    }
    if work_id in {"arxiv:2210.03629", "arxiv:2310.11511"}:
        materials = call(
            "/materials?" + urlencode({"work_id": work_id, "version_id": version["version_id"]})
        )
        material = next(m for m in materials if m["scope"] == "excerpt" and 3 in m["page_numbers"])
        document = call("/materials/" + material["material_id"])
        span = next(s for s in document["spans"] if s["page"] == 3 and s["end"] - s["start"] >= 180)
        start, end = span["start"], span["start"] + 180
        reference.update(
            anchor=f"material:{material['material_id']}:page:3:{start}:{end}",
            material_id=material["material_id"],
            material_hash=material["content_hash"],
            parser_revision=material["parser_revision"],
            source_scope="excerpt",
        )
    else:
        assert len(version["abstract"]) >= 180, "No fabricated excerpt or source expansion"
    project_id = identity("project", name)
    project_data = {
        "title": "Example · " + name,
        "question": question,
        "scope": "Agent-authored walkthrough example, not your authored research or usefulness judgment. Selected retained public material only.",
        "constraints": "Manual reading only. No provider calls, generated findings or experiment execution. Retained excerpts are not the complete paper.",
        "next_actions": [
            "Read the exact highlighted passage.",
            "Write an assumption or an unanswered question in your own words.",
        ],
        "status": "active",
    }
    existing = next((p for p in index["projects"] if p["id"] == project_id), None)
    if existing:
        assert existing["data"] == project_data, (
            "Example edited; preserve it instead of overwriting"
        )
        project = call("/context/projects/" + project_id)
    else:
        project = call(
            "/context/projects",
            {
                "id": project_id,
                "revision": 0,
                "request_id": "walkthrough-create-" + project_id,
                "data": project_data,
                "initial_source": reference,
            },
        )
    source = next(
        (
            s
            for s in project["sources"]
            if s["role"] == "evidence" and s["reference"]["anchor"] == reference["anchor"]
        ),
        None,
    )
    if source is None:
        project = call(
            "/context/projects/" + project_id + "/sources",
            {
                "revision": project["revision"],
                "request_id": "walkthrough-evidence-" + project_id,
                "role": "evidence",
                "label": "Example selected passage · source identity is not factual-support validation",
                "reference": reference,
            },
        )
    entry_id = identity("example-question", name)
    entry_data = {
        "work_id": work_id,
        "version_id": version["version_id"],
        "kind": "question",
        "body": "Example question (agent-authored, not your judgment): " + question,
        "anchor": reference["anchor"],
    }
    context = {
        "mode": "research",
        "project_id": project_id,
        "thread_id": None,
        "return_to": "/workspace/projects?mode=research&project=" + project_id,
    }
    current_state = call("/context/state?mode=learn")
    entry = next(
        (e for w in current_state["works"] for e in w["entries"] if e["id"] == entry_id), None
    )
    if entry:
        assert all(entry[k] == v for k, v in entry_data.items()), "Example note edited; preserve it"
        assert entry["context"] == context
    else:
        entry = call(
            "/context/entries",
            {
                "id": entry_id,
                "revision": 0,
                "request_id": "walkthrough-question-" + project_id,
                "data": entry_data,
                "context": context,
            },
        )
    if not any(e["entry_id"] == entry_id for e in project["entries"]):
        project = call(
            "/context/projects/" + project_id + "/entries",
            {
                "revision": project["revision"],
                "request_id": "walkthrough-entry-link-" + project_id,
                "entry_id": entry_id,
                "entry_revision": entry["revision"],
            },
        )
    thread_id = identity("thread", name)
    thread_data = {
        "title": "Example · " + prerequisite,
        "goal": "Agent-authored example learning goal: " + goal,
        "prerequisite": prerequisite,
        "status": "active",
        "origin": context,
        "source": reference,
        "entry": {"entry_id": entry_id, "entry_revision": entry["revision"]},
    }
    existing_thread = next((t for t in index["threads"] if t["id"] == thread_id), None)
    if existing_thread:
        assert existing_thread["data"] == LearningThreadData.model_validate(thread_data).model_dump(
            mode="json"
        ), "Example thread edited; preserve it"
    else:
        call(
            "/context/threads",
            {
                "id": thread_id,
                "revision": 0,
                "request_id": "walkthrough-thread-" + project_id,
                "data": thread_data,
            },
        )
    receipts.append(
        {
            "project_id": project_id,
            "title": project_data["title"],
            "question_id": entry_id,
            "thread_id": thread_id,
            "source": reference,
            "project_url": "http://127.0.0.1:3178" + context["return_to"],
        }
    )
after = call("/context/state?mode=learn")
assert digest(after["profile"]) == before_profile
assert digest(after["sources"]) == before_sources
assert not after["schedule"]["enabled"]
receipt = {
    "principal": "modes-preview",
    "api": BASE,
    "label": "Agent-authored walkthrough examples, not owner work or judgments",
    "examples": receipts,
    "profile_unchanged": True,
    "source_health_unchanged": True,
    "source_requests": 0,
    "provider_contacts": 0,
    "recurrence": False,
}
(OUT / "walkthrough-examples.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(
    json.dumps(
        {
            "examples": len(receipts),
            "profile_unchanged": True,
            "provider_contacts": 0,
            "source_requests": 0,
        }
    )
)
