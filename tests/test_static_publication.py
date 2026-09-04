"""WO-W16 static publication build and built-byte gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.content.loader import load_path_dir
from src.content.static_publication import (
    _safe_waitlist_url,
    build_publication,
    main,
    validate_artifact,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
REAL_PATH = ROOT / "content" / "paths" / "reading-first-papers"
FIXTURE_PATH = ROOT / "content" / "paths" / "fixture-guided-read"


class TestDecisionGates:
    def test_real_path_cannot_publish_while_review_decisions_are_open(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not 'published'.*W-OD-2/3"):
            build_publication(
                REAL_PATH,
                tmp_path / "public",
                waitlist_url="mailto:waitlist@example.com",
            )

    def test_fixture_can_never_be_a_production_publication(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="non-fixture flagship"):
            build_publication(
                FIXTURE_PATH,
                tmp_path / "public",
                waitlist_url="https://example.com/form",
            )

    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com/form",
            "javascript:alert(1)",
            "/api/waitlist",
            "https://",
            "mailto:",
        ],
    )
    def test_waitlist_must_be_owner_selected_external_https_or_mailto(self, url: str) -> None:
        with pytest.raises(ValueError, match="https form or mailto"):
            _safe_waitlist_url(url)

    @pytest.mark.parametrize(
        "url", ["https://forms.example.com/waitlist", "mailto:hello@example.com"]
    )
    def test_allowed_waitlist_shapes(self, url: str) -> None:
        assert _safe_waitlist_url(url) == url


class TestPreviewArtifact:
    def test_real_preview_is_noindex_and_collects_nothing(self, tmp_path: Path) -> None:
        output = tmp_path / "preview"
        emitted = build_publication(REAL_PATH, output, preview=True)
        assert len(emitted) == 3  # index, CSS, metadata; real companions are gated.
        index = (output / "index.html").read_text(encoding="utf-8")
        assert "noindex,nofollow" in index
        assert "Review preview · not published" in index
        assert "Waitlist opens after owner approval" in index
        assert "Join the waitlist" not in index
        assert "Companion awaiting review" in index
        assert "The argument spine" in index

    def test_fixture_preview_renders_companions_without_raw_html(self, tmp_path: Path) -> None:
        output = tmp_path / "fixture"
        emitted = build_publication(FIXTURE_PATH, output, preview=True)
        assert len(emitted) == 6  # index, CSS, metadata, three companions.
        companion = (output / "briefings" / "01.html").read_text(encoding="utf-8")
        assert "FIXTURE CONTENT" in companion
        assert "Why this paper, why now" in companion
        assert "<script" not in companion.lower()
        assert 'href="../style.css"' in companion

    def test_built_artifact_contains_every_link_and_attribution(self, tmp_path: Path) -> None:
        output = tmp_path / "preview"
        build_publication(REAL_PATH, output, preview=True)
        combined = "\n".join(
            path.read_text(encoding="utf-8") for path in output.rglob("*") if path.is_file()
        )
        manifest = load_path_dir(REAL_PATH).manifest
        for entry in manifest.entries:
            assert entry.canonical_url in combined
            assert entry.attribution in combined
        assert "/pdf/" not in combined
        assert ".pdf" not in combined

    @pytest.mark.parametrize(
        "smuggled",
        [
            '<script src="tracker.js"></script>',
            '<a href="/api/waitlist">join</a>',
            "ANTHROPIC_API_KEY=secret",
            "http://localhost:8000/research",
        ],
    )
    def test_validator_checks_built_bytes_not_only_source(
        self, tmp_path: Path, smuggled: str
    ) -> None:
        output = tmp_path / "preview"
        build_publication(REAL_PATH, output, preview=True)
        index = output / "index.html"
        index.write_text(index.read_text(encoding="utf-8") + smuggled, encoding="utf-8")
        with pytest.raises(ValueError, match="forbidden pattern"):
            validate_artifact(
                output,
                entries=load_path_dir(REAL_PATH).manifest.entries,
                production=False,
            )

    def test_nonempty_output_is_refused_instead_of_overwritten(self, tmp_path: Path) -> None:
        output = tmp_path / "preview"
        output.mkdir()
        (output / "owner-file.txt").write_text("keep", encoding="utf-8")
        with pytest.raises(ValueError, match="absent or empty"):
            build_publication(REAL_PATH, output, preview=True)
        assert (output / "owner-file.txt").read_text(encoding="utf-8") == "keep"

    def test_cli_builds_preview(self, tmp_path: Path) -> None:
        output = tmp_path / "preview"
        assert (
            main(
                [
                    "--path-dir",
                    str(REAL_PATH),
                    "--output",
                    str(output),
                    "--preview",
                ]
            )
            == 0
        )
        assert (output / "index.html").is_file()
