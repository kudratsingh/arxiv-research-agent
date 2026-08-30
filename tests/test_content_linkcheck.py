"""Link-rot checking: what counts as broken, and what only looks broken.

No network. The session is a stub, because the interesting cases are the
ones a live run would not reproduce on demand — a host that rejects
`HEAD`, a connection that never opens, a redirect chain that ends
somewhere fine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from src.content import loader
from src.content.linkcheck import (
    LinkTarget,
    check_links,
    check_target,
    collect_targets,
    main,
    render_report,
)
from src.content.loader import default_content_root, load_content_root

pytestmark = pytest.mark.unit


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def close(self) -> None:
        return None


class _StubSession:
    """Records calls and answers from a scripted per-URL status map."""

    def __init__(
        self,
        head: dict[str, int] | None = None,
        get: dict[str, int] | None = None,
        raises: set[str] | None = None,
    ) -> None:
        self.head_map = head or {}
        self.get_map = get or {}
        self.raises = raises or set()
        self.calls: list[tuple[str, str]] = []

    def head(self, url: str, **_: Any) -> _Response:
        self.calls.append(("HEAD", url))
        if url in self.raises:
            raise requests.ConnectionError("refused")
        return _Response(self.head_map.get(url, 200))

    def get(self, url: str, **_: Any) -> _Response:
        self.calls.append(("GET", url))
        if url in self.raises:
            raise requests.ConnectionError("refused")
        return _Response(self.get_map.get(url, 200))


def _target(url: str) -> LinkTarget:
    return LinkTarget("p", "arxiv:1706.03762", "canonical_url", url)


class TestCheckTarget:
    def test_a_200_is_ok(self) -> None:
        session = _StubSession()
        result = check_target(session, _target("https://example.org/"), timeout=1)
        assert result.ok
        assert result.method == "HEAD"

    def test_a_head_refusal_is_retried_as_a_get(self) -> None:
        """A host that dislikes HEAD is not a dead link."""
        url = "https://example.org/"
        session = _StubSession(head={url: 405}, get={url: 200})
        result = check_target(session, _target(url), timeout=1)
        assert result.ok
        assert result.method == "GET"
        assert session.calls == [("HEAD", url), ("GET", url)]

    def test_a_real_404_survives_the_get_retry(self) -> None:
        url = "https://example.org/gone"
        session = _StubSession(head={url: 404}, get={url: 404})
        result = check_target(session, _target(url), timeout=1)
        assert not result.ok
        assert result.status_code == 404
        assert result.detail == "HTTP 404"

    def test_a_transport_failure_is_a_result_not_an_exception(self) -> None:
        """A checker that raises stops checking the rest of the path."""
        url = "https://nowhere.invalid/"
        session = _StubSession(raises={url})
        result = check_target(session, _target(url), timeout=1)
        assert not result.ok
        assert result.status_code is None
        assert "ConnectionError" in result.detail

    @pytest.mark.parametrize("status", [301, 302, 307, 399])
    def test_an_unfollowed_redirect_status_is_not_ok(self, status: int) -> None:
        """Redirects are followed; a 3xx *result* means the chain ended there."""
        url = "https://example.org/moved"
        session = _StubSession(head={url: status})
        result = check_target(session, _target(url), timeout=1)
        assert not result.ok


class TestCollectAndReport:
    def test_every_url_a_manifest_publishes_is_collected(self) -> None:
        paths = load_content_root(default_content_root())
        targets = collect_targets(paths.values())
        fields = {t.field for t in targets}
        assert fields == {
            "canonical_url",
            "license_url",
            "sequencing.evidence_url",
        }
        # Every entry contributes its canonical URL, none is skipped.
        entries = sum(len(p.manifest.entries) for p in paths.values())
        assert sum(1 for t in targets if t.field == "canonical_url") == entries

    def test_the_report_ends_with_the_broken_links(self) -> None:
        session = _StubSession(
            head={"https://example.org/gone": 404},
            get={"https://example.org/gone": 404},
        )
        results = check_links(
            [_target("https://example.org/"), _target("https://example.org/gone")],
            session=session,
            delay_sec=0,
        )
        report = render_report(results)
        assert report.splitlines()[0] == "2 link(s) checked, 1 ok, 1 broken"
        assert report.rstrip().endswith("(HTTP 404)")

    def test_checking_is_paced_per_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two requests to one host wait; two hosts do not wait on each other."""
        slept: list[float] = []
        monkeypatch.setattr(
            "src.content.linkcheck.time.sleep", lambda s: slept.append(s)
        )
        session = _StubSession()
        check_links(
            [
                _target("https://a.example/1"),
                _target("https://b.example/1"),
                _target("https://a.example/2"),
            ],
            session=session,
            delay_sec=5.0,
        )
        assert len(slept) == 1


class TestCli:
    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        loader.clear_cache()

    def test_invalid_content_exits_two_before_any_request(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        directory = tmp_path / "paths" / "broken"
        directory.mkdir(parents=True)
        (directory / "path.json").write_text("{ not json", encoding="utf-8")
        assert main(["--root", str(tmp_path)]) == 2
        assert "before any link was checked" in capsys.readouterr().err

    def test_an_empty_root_checks_nothing_and_succeeds(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--root", str(tmp_path)]) == 0
        assert "0 link(s) checked" in capsys.readouterr().out

    def test_json_output_is_machine_readable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        document = _minimal_document()
        directory = tmp_path / "paths" / document["path_id"]
        directory.mkdir(parents=True)
        (directory / "path.json").write_text(json.dumps(document), encoding="utf-8")
        monkeypatch.setattr(
            "src.content.linkcheck.build_retrying_session", _StubSession
        )
        assert main(["--root", str(tmp_path), "--json", "--delay", "0"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload[0]["field"] == "canonical_url"
        assert payload[0]["ok"] is True


def _minimal_document() -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "path_id": "link-path",
        "kind": "flagship",
        "title": "Link path",
        "goal": "Have one URL.",
        "version": 1,
        "status": "proposed",
        "updated_at": "2026-08-30",
        "fixture": False,
        "licensing": {
            "posture_id": "W-OD-3",
            "full_text": "link-out-only",
            "abstracts": "displayed-with-attribution",
            "quotes": "sparing-and-attributed",
            "s2_derived_facts": "link-back-required",
            "commercial_use": "none-through-phase-w",
            "counsel_confirmed": False,
            "source": "planning/07-learning-platform/02-CONTENT.md#22-papers",
        },
        "review": {
            "owner": "kudratsingh",
            "decisions": ["W-OD-3"],
            "curation_minutes_per_entry": 10,
        },
        "entries": [
            {
                "position": 1,
                "resource_id": "arxiv:1706.03762",
                "kind": "paper",
                "title": "Attention Is All You Need",
                "authors": ["Ashish Vaswani"],
                "author_count": 8,
                "year": 2017,
                "canonical_url": "https://arxiv.org/abs/1706.03762",
                "license_note": "Link out to the arXiv abs page.",
                "attribution": "Vaswani et al. (arXiv.org)",
                "provenance": "curated",
                "status": "proposed",
                "rationale": "A rationale long enough to read like a sentence.",
                "vocabulary": ["self-attention"],
                "est_minutes": 90,
                "sequencing": {"method": "editorial", "cites": []},
            }
        ],
    }
