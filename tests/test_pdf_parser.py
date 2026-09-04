"""Unit tests for pdf_parser — pure logic and cache behavior only.

Download and PyMuPDF extraction are intentionally not exercised here;
those require network and a real PDF and belong in integration tests.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.tools import pdf_parser as pdf_parser_mod
from src.tools.paper_cache import DiskPaperCache
from src.tools.pdf_parser import (
    _cache_key,
    _download_pdf,
    _is_fetchable,
    _upgrade_arxiv_scheme,
    parse_pdf,
)

pytestmark = pytest.mark.unit


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


# ---------------------------------------------------------------------------
# SSRF destination guard — ADR 0041
# ---------------------------------------------------------------------------


def _fake_getaddrinfo(address: str):  # type: ignore[no-untyped-def]
    """getaddrinfo stub resolving every host to `address`."""

    def _resolver(host: str, port: object, *args: object, **kwargs: object) -> list:
        return [(2, 1, 6, "", (address, 0))]

    return _resolver


# The fetchability boundary: scheme upgrade, DNS-based private-range
# refusal and per-hop redirect revalidation are the SSRF defence, so
# they are selectable on their own with `pytest -m security`.
@pytest.mark.security
class TestUpgradeArxivScheme:
    def test_http_arxiv_upgraded_to_https(self) -> None:
        assert (
            _upgrade_arxiv_scheme("http://arxiv.org/pdf/2311.09000")
            == "https://arxiv.org/pdf/2311.09000"
        )

    def test_non_arxiv_http_left_alone(self) -> None:
        # Not upgraded — it gets *rejected* by `_is_fetchable` instead,
        # since we can't know that an arbitrary host serves https.
        assert (
            _upgrade_arxiv_scheme("http://example.com/paper.pdf")
            == "http://example.com/paper.pdf"
        )


@pytest.mark.security
class TestIsFetchable:
    def test_arxiv_https_trusted_without_dns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _no_dns(*_a: object, **_kw: object) -> list:
            raise AssertionError("arXiv hosts must not trigger a DNS pre-flight")

        monkeypatch.setattr(pdf_parser_mod.socket, "getaddrinfo", _no_dns)
        assert _is_fetchable("https://arxiv.org/pdf/2311.09000") is True

    def test_plain_http_rejected(self) -> None:
        assert _is_fetchable("http://example.com/paper.pdf") is False

    def test_public_host_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            pdf_parser_mod.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34")
        )
        assert _is_fetchable("https://example.com/paper.pdf") is True

    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",  # loopback
            "10.1.2.3",  # private
            "169.254.169.254",  # link-local (cloud metadata endpoint)
            "192.168.1.10",  # private
            "0.0.0.0",  # unspecified
            "::1",  # v6 loopback
        ],
    )
    def test_non_public_addresses_rejected(
        self, monkeypatch: pytest.MonkeyPatch, address: str
    ) -> None:
        monkeypatch.setattr(
            pdf_parser_mod.socket, "getaddrinfo", _fake_getaddrinfo(address)
        )
        assert _is_fetchable("https://evil.example/paper.pdf") is False

    def test_dns_failure_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _nxdomain(*_a: object, **_kw: object) -> list:
            raise OSError("Name or service not known")

        monkeypatch.setattr(pdf_parser_mod.socket, "getaddrinfo", _nxdomain)
        assert _is_fetchable("https://gone.example/paper.pdf") is False


@pytest.mark.security
class TestDownloadRedirectValidation:
    def _redirect_response(self, location: str) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 302
        resp.headers = {"Location": location}
        return resp

    def _pdf_response(self) -> MagicMock:
        body = b"%PDF-1.4\n" + b"x" * 64
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"Content-Length": str(len(body))}
        resp.iter_content = MagicMock(return_value=iter([body]))
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_redirect_into_internal_address_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A public host 302ing to the cloud metadata endpoint must not
        be followed — this is the hop-revalidation the blanket
        `allow_redirects=True` never did."""
        monkeypatch.setattr(
            pdf_parser_mod.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34")
        )
        with patch("src.tools.pdf_parser.build_retrying_session") as factory:
            factory.return_value.get.return_value = self._redirect_response(
                "http://169.254.169.254/latest/meta-data/"
            )
            ok = _download_pdf("https://journal.example/p.pdf", tmp_path / "o.pdf")
        assert ok is False

    def test_redirect_to_public_https_followed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            pdf_parser_mod.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34")
        )
        responses = [
            self._redirect_response("https://cdn.example/real.pdf"),
            self._pdf_response(),
        ]
        with patch("src.tools.pdf_parser.build_retrying_session") as factory:
            factory.return_value.get.side_effect = responses
            ok = _download_pdf("https://journal.example/p.pdf", tmp_path / "o.pdf")
        assert ok is True
        assert (tmp_path / "o.pdf").read_bytes().startswith(b"%PDF-")

    def test_http_arxiv_url_fetched_over_https(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen_urls: list[str] = []

        def _get(url: str, **_kw: object) -> MagicMock:
            seen_urls.append(url)
            return self._pdf_response()

        with patch("src.tools.pdf_parser.build_retrying_session") as factory:
            factory.return_value.get.side_effect = _get
            ok = _download_pdf("http://arxiv.org/pdf/2311.09000", tmp_path / "o.pdf")
        assert ok is True
        assert seen_urls == ["https://arxiv.org/pdf/2311.09000"]

    def test_redirect_loop_gives_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            pdf_parser_mod.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34")
        )
        with patch("src.tools.pdf_parser.build_retrying_session") as factory:
            factory.return_value.get.return_value = self._redirect_response(
                "https://journal.example/p.pdf"
            )
            ok = _download_pdf("https://journal.example/p.pdf", tmp_path / "o.pdf")
        assert ok is False
