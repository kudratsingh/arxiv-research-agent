"""Unit tests for pdf_parser — pure logic and cache behavior only.

Download and PyMuPDF extraction are intentionally not exercised here;
those require network and a real PDF and belong in integration tests.
"""

from pathlib import Path

from src.tools.paper_cache import DiskPaperCache
from src.tools.pdf_parser import _cache_key, parse_pdf


class TestCacheKey:
    def test_extracts_arxiv_id_from_pdf_url(self) -> None:
        assert _cache_key("http://arxiv.org/pdf/2311.09000") == "2311.09000"

    def test_extracts_arxiv_id_with_version(self) -> None:
        assert _cache_key("http://arxiv.org/pdf/2311.09000v2") == "2311.09000v2"

    def test_extracts_arxiv_id_with_suffix(self) -> None:
        assert _cache_key("http://arxiv.org/pdf/2311.09000v2.pdf") == "2311.09000v2"

    def test_hashes_non_arxiv_url(self) -> None:
        key = _cache_key("https://example.com/paper.pdf")
        assert len(key) == 16
        assert all(c in "0123456789abcdef" for c in key)

    def test_stable_hash_for_same_url(self) -> None:
        url = "https://example.com/paper.pdf"
        assert _cache_key(url) == _cache_key(url)


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
