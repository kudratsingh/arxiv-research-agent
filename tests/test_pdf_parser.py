"""Unit tests for pdf_parser — pure logic and cache behavior only.

Download and PyMuPDF extraction are intentionally not exercised here;
those require network and a real PDF and belong in integration tests.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.tools.paper_cache import DiskPaperCache
from src.tools.pdf_parser import _cache_key, _download_pdf, parse_pdf


class TestCacheKey:
    def test_extracts_arxiv_id_from_pdf_url(self) -> None:
        assert _cache_key("https://arxiv.org/pdf/2311.09000") == "2311.09000"

    def test_extracts_arxiv_id_with_version(self) -> None:
        assert _cache_key("https://arxiv.org/pdf/2311.09000v2") == "2311.09000v2"

    def test_extracts_arxiv_id_with_suffix(self) -> None:
        assert _cache_key("https://arxiv.org/pdf/2311.09000v2.pdf") == "2311.09000v2"

    def test_hashes_non_arxiv_url(self) -> None:
        key = _cache_key("https://example.com/paper.pdf")
        assert len(key) == 16
        assert all(c in "0123456789abcdef" for c in key)

    def test_stable_hash_for_same_url(self) -> None:
        url = "https://example.com/paper.pdf"
        assert _cache_key(url) == _cache_key(url)

    def test_offhost_url_masquerading_as_arxiv_id_hashes(self) -> None:
        """ADR 0033 guard: a non-arxiv.org host with an arXiv-ID-shaped
        path must NOT share a cache slot with the real arXiv paper.

        The old regex-only cache key let `https://evil.com/2311.09000/
        attack.pdf` poison the cache slot for arxiv.org's real 2311.09000.
        """
        legit = _cache_key("https://arxiv.org/pdf/2311.09000")
        evil = _cache_key("https://evil.com/2311.09000/attack.pdf")
        assert legit == "2311.09000"
        assert evil != legit
        # Non-arxiv path takes the SHA fallback shape.
        assert len(evil) == 16


class TestDownloadPdf:
    """Streaming size cap — ADR 0033."""

    def _mock_streaming_response(
        self,
        chunks: list[bytes],
        status: int = 200,
        content_length: str | None = None,
    ) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status
        resp.headers = {} if content_length is None else {"Content-Length": content_length}
        resp.iter_content = MagicMock(return_value=iter(chunks))
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    # Floor of `settings.pdf_max_bytes` is 1 MiB — use realistic
    # values in tests rather than skirting the validator.
    _CAP = 2 * 1024 * 1024
    _OVER = 5 * 1024 * 1024

    def test_rejects_declared_oversize_before_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Content-Length above the cap must abort before any bytes flow."""
        from src.config import Settings
        from src.tools import pdf_parser as pdf_parser_module

        monkeypatch.setattr(
            pdf_parser_module, "settings", Settings(pdf_max_bytes=self._CAP)
        )
        resp = self._mock_streaming_response(
            chunks=[], content_length=str(self._OVER)
        )

        with patch(
            "src.tools.pdf_parser.build_retrying_session"
        ) as fake_session_factory:
            fake_session_factory.return_value.get.return_value = resp
            ok = _download_pdf(
                "https://arxiv.org/pdf/2311.09000", tmp_path / "out.pdf"
            )

        assert ok is False
        resp.iter_content.assert_not_called()

    def test_stops_streaming_when_over_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No Content-Length: cap must fire mid-stream once bytes cross the limit."""
        from src.config import Settings
        from src.tools import pdf_parser as pdf_parser_module

        monkeypatch.setattr(
            pdf_parser_module, "settings", Settings(pdf_max_bytes=self._CAP)
        )
        # Server omits Content-Length; two chunks together cross the cap.
        chunk = b"A" * (self._CAP - 1024)
        resp = self._mock_streaming_response(chunks=[chunk, chunk])
        with patch(
            "src.tools.pdf_parser.build_retrying_session"
        ) as fake_session_factory:
            fake_session_factory.return_value.get.return_value = resp
            ok = _download_pdf(
                "https://arxiv.org/pdf/2311.09000", tmp_path / "out.pdf"
            )
        assert ok is False
        assert not (tmp_path / "out.pdf").exists()

    def test_accepts_pdf_under_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.config import Settings
        from src.tools import pdf_parser as pdf_parser_module

        monkeypatch.setattr(
            pdf_parser_module, "settings", Settings(pdf_max_bytes=self._CAP)
        )
        pdf_bytes = b"%PDF-1.4\n" + b"x" * 128
        resp = self._mock_streaming_response(
            chunks=[pdf_bytes], content_length=str(len(pdf_bytes))
        )
        with patch(
            "src.tools.pdf_parser.build_retrying_session"
        ) as fake_session_factory:
            fake_session_factory.return_value.get.return_value = resp
            dest = tmp_path / "ok.pdf"
            ok = _download_pdf("https://arxiv.org/pdf/2311.09000", dest)
        assert ok is True
        assert dest.exists()
        assert dest.read_bytes().startswith(b"%PDF-")


class TestParsePdf:
    def test_empty_url_returns_empty_string(self, tmp_path: Path) -> None:
        assert parse_pdf("", cache_dir=tmp_path) == ""

    def test_returns_cached_text_when_txt_exists(self, tmp_path: Path) -> None:
        # PR 4 refactor: `cache_dir` is now the raw-PDF path only; the
        # extracted-text cache is the pluggable `PaperCache`. Inject a
        # `DiskPaperCache` pointing at tmp_path so the write we do
        # here lines up with the read parse_pdf performs.
        url = "http://arxiv.org/pdf/2311.09000"
        (tmp_path / "2311.09000.txt").write_text("cached body", encoding="utf-8")

        # Must not hit the network or open PyMuPDF — the cache short-circuits.
        assert (
            parse_pdf(url, cache_dir=tmp_path, cache=DiskPaperCache(tmp_path))
            == "cached body"
        )

    def test_cache_dir_accepts_string_path(self, tmp_path: Path) -> None:
        url = "http://arxiv.org/pdf/2311.09000"
        (tmp_path / "2311.09000.txt").write_text("ok", encoding="utf-8")
        assert (
            parse_pdf(url, cache_dir=str(tmp_path), cache=DiskPaperCache(tmp_path))
            == "ok"
        )
