"""Metadata boundaries: public pinned TLS, honest dates, identities and receipts."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import urllib3

from src.workspace import intake as m
from src.workspace import rate_limit

pytestmark = pytest.mark.unit
NOW = datetime(2026, 11, 2, 16, tzinfo=UTC)


@pytest.mark.parametrize("host,group,interval", [
    ("rss.arxiv.org", "arxiv", 3.1),
    ("export.arxiv.org", "arxiv", 3.1),
    ("huggingface.co", "huggingface.co", 1.0),
])
def test_configured_shared_governor_is_used_without_local_fallback(
    monkeypatch: pytest.MonkeyPatch, host: str, group: str, interval: float
) -> None:
    calls: list[tuple[str, str, float]] = []

    @contextlib.contextmanager
    def slot(database: str, name: str, spacing: float) -> Any:
        calls.append((database, name, spacing))
        yield

    monkeypatch.setenv("WORKSPACE_RATE_DATABASE_URL", "postgresql://verification")
    monkeypatch.setattr(rate_limit, "shared_rate_slot", slot)
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("local fallback"))
    with m._rate_slot(host):
        assert calls == [("postgresql://verification", group, interval)]
    # Body errors are not rewritten as governor failures.
    with pytest.raises(m.IntakeError, match="source_unavailable"), m._rate_slot(host):
        raise m.IntakeError("source_unavailable", request_count=1)


def test_shared_governor_failure_refuses_before_request(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextlib.contextmanager
    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise rate_limit.SharedRateError("shared_source_rate_unavailable")
        yield  # pragma: no cover - contextmanager protocol

    monkeypatch.setenv("WORKSPACE_RATE_DATABASE_URL", "postgresql://verification")
    monkeypatch.setattr(rate_limit, "shared_rate_slot", unavailable)
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("local fallback"))
    with (
        pytest.raises(m.IntakeError, match="shared_source_rate_unavailable") as error,
        m._rate_slot("rss.arxiv.org"),
    ):
        pytest.fail("request must not start")
    assert error.value.request_count == 0


def test_default_ports_do_not_merge_distinct_manual_url_identities() -> None:
    assert m.normalize_url("https://example.org:443/paper") == "https://example.org/paper"
    assert m.normalize_url("http://example.org:80/paper") == "http://example.org/paper"
    assert m.normalize_url("https://example.org:80/paper") == "https://example.org:80/paper"
    assert m.normalize_manual("https://example.org:80/paper")["work_id"] != m.normalize_manual("https://example.org/paper")["work_id"]
    with pytest.raises(m.IntakeError):
        m.validate_fetch_url("https://rss.arxiv.org:80/rss/cs.AI")
RSS = b"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:arxiv="http://arxiv.org/schemas/atom"><channel><item><title>A retrieval agent</title><link>https://arxiv.org/abs/2611.00001</link><guid>oai:arXiv.org:2611.00001v2</guid><description>arXiv:2611.00001v2 Announce Type: replace Abstract: An agent checks retrieval.</description><pubDate>Mon, 02 Nov 2026 00:00:00 -0500</pubDate><dc:creator>Alice, Bob</dc:creator><category>cs.AI</category><arxiv:DOI>10.1234/Test</arxiv:DOI></item></channel></rss>"""
BLOG = b"""<rss><channel><item><title>Retrieval &amp; agents</title><link>https://huggingface.co/blog/retrieval?utm_source=reader</link><description><![CDATA[<p>Useful <b>context</b>.</p><script>steal()</script><img src=x onerror=steal()>]]></description><pubDate>Mon, 02 Nov 2026 00:00:00 +0000</pubDate></item></channel></rss>"""


def transport(
    body: bytes = BLOG,
    status: int = 200,
    headers: dict[str, str] | None = None,
    url: str = m.SOURCES["hugging-face-blog"].url,
) -> Any:
    def fetch(request_url: str, request_headers: dict[str, str]) -> m.HttpResponse:
        return m.HttpResponse(
            status, headers or {"Content-Type": "application/rss+xml", "ETag": '"v1"'}, body, url
        )

    return fetch


def test_arxiv_replacement_is_not_original_publication_and_version_is_stable() -> None:
    item = m.parse_feed(RSS, "arxiv-cs-ai", now=NOW)[0]
    assert item["work_id"] == "arxiv:2611.00001"
    assert item["version_id"] == "arxiv:2611.00001:v2"
    assert item["url"] == "https://arxiv.org/abs/2611.00001v2"
    assert item["published_at"] is None
    assert item["published_precision"] == "unknown"
    assert item["updated_at"] is None
    assert item["announced_at"] == "2026-11-02T05:00:00Z"
    assert item["announce_type"] == "replace"
    assert item["abstract"] == "An agent checks retrieval."
    assert item["authors"] == ["Alice", "Bob"]
    assert item["categories"] == ["cs.AI"]
    assert item["aliases"] == ["doi:10.1234/test"]
    assert item["access_state"] == "abstract"
    assert m.parse_feed(RSS, "arxiv-cs-lg", now=NOW)[0]["version_id"] == item["version_id"]


def test_arxiv_new_and_explicit_announce_type() -> None:
    item = m.parse_feed(
        RSS.replace(b"replace", b"new").replace(
            b"</item>", b"<arxiv:announce_type>new</arxiv:announce_type></item>"
        ),
        "arxiv-cs-ai",
        now=NOW,
    )[0]
    assert item["published_at"] is None and item["updated_at"] is None
    assert item["announced_at"] == "2026-11-02T05:00:00Z"


def test_blog_sanitization_observed_versions_and_unknown_dates() -> None:
    item = m.parse_feed(BLOG, "hugging-face-blog", now=NOW)[0]
    assert item["abstract"] == "Useful context."
    assert "script" not in item["abstract"] and "steal" not in item["abstract"]
    assert item["url"] == "https://huggingface.co/blog/retrieval"
    assert item["source_scope"] == "excerpt"
    revised = m.parse_feed(BLOG.replace(b"Useful", b"Changed"), "hugging-face-blog", now=NOW)[0]
    assert item["work_id"] == revised["work_id"]
    assert item["version_id"] != revised["version_id"]
    missing = m.parse_feed(
        BLOG.replace(b"<pubDate>Mon, 02 Nov 2026 00:00:00 +0000</pubDate>", b""),
        "hugging-face-blog",
        now=NOW,
    )[0]
    assert missing["published_at"] is None
    assert missing["first_seen_at"] == "2026-11-02T16:00:00Z"


def test_atom_and_unversioned_arxiv_are_not_invented_v1() -> None:
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://arxiv.org/abs/hep-th/9901001</id><title>Old paper</title><link rel="self" href="https://arxiv.org/api/no"/><link href="https://arxiv.org/abs/hep-th/9901001"/><summary>Abstract</summary><published>1999-01-01</published><updated>2026-11-01T10:00:00Z</updated><author><name>Alice</name></author><category term="hep-th"/></entry></feed>"""
    item = m.parse_feed(atom, "arxiv-cs-lg", now=NOW)[0]
    assert item["version_label"].startswith("observed ")
    assert item["version_id"].startswith("arxiv:hep-th/9901001:observed-")
    assert item["published_precision"] == "date"
    assert item["authors"] == ["Alice"] and item["categories"] == ["hep-th"]


def test_parse_skips_missing_malicious_entries_and_deduplicates() -> None:
    entries = BLOG.split(b"<item>")[1].split(b"</item>")[0]
    data = (
        b"<rss><channel><item>"
        + entries
        + b"</item><item>"
        + entries
        + b"</item><item><title>Missing URL</title></item><item><title>Bad</title><link>javascript:alert(1)</link></item><item><title>Foreign</title><link>https://evil.com/post</link></item></channel></rss>"
    )
    assert len(m.parse_feed(data, "hugging-face-blog", now=NOW)) == 1
    assert not m.parse_feed(
        b"<rss><channel><item><title>No id</title><link>https://arxiv.org/abs/not-id</link></item></channel></rss>",
        "arxiv-cs-ai",
        now=NOW,
    )
    item = m.parse_feed(
        BLOG.replace(b"<description>", b"<unavailable>").replace(
            b"</description>", b"</unavailable>"
        ),
        "hugging-face-blog",
        now=NOW,
    )[0]
    assert item["source_scope"] == "metadata"


@pytest.mark.parametrize(
    "data,reason",
    [
        (b"<bad/>", "invalid_feed_root"),
        (b"not XML", "invalid_feed"),
        (b'<!DOCTYPE x [<!ENTITY foo "expanded">]><rss>&foo;</rss>', "invalid_feed"),
        (b"x" * (m.MAX_BYTES + 1), "response_too_large"),
    ],
)
def test_feed_document_bounds(data: bytes, reason: str) -> None:
    with pytest.raises(m.IntakeError, match=reason):
        m.parse_feed(data, "hugging-face-blog", now=NOW)


def test_success_receipt_conditional_headers_and_safe_commit_inputs() -> None:
    def fetch(url: str, headers: dict[str, str]) -> m.HttpResponse:
        assert headers["If-None-Match"] == '"old"'
        assert headers["If-Modified-Since"] == "yesterday"
        return m.HttpResponse(200, {"ETag": '"new"', "Last-Modified": "today"}, BLOG, url)

    result = m.fetch_source(
        "hugging-face-blog",
        {"etag": '"old"', "last_modified": "yesterday"},
        now=NOW,
        transport=fetch,
    )
    assert result.validators == {"etag": '"new"', "last_modified": "today"}
    assert result.receipt["status"] == "success"
    assert result.receipt["request_count"] == 1
    assert result.receipt["successful_window"]["basis"] == "returned_item_dates_only"
    assert result.receipt["requested_window"]["start"] == "2026-10-26T16:00:00Z"
    assert result.receipt["source_record_ids"] == [result.items[0]["source_record_id"]]
    assert result.receipt["response_hash"]


def test_bound_and_overlap_preserve_late_updates_and_unknown_dates() -> None:
    # 26 eligible distinct works; a late-updated old arXiv record remains eligible.
    many = (
        b"<rss><channel>"
        + b"".join(
            BLOG.split(b"<item>")[1]
            .split(b"</item>")[0]
            .replace(b"/blog/retrieval", f"/blog/{i}".encode())
            .join((b"<item>", b"</item>"))
            for i in range(26)
        )
        + b"</channel></rss>"
    )
    result = m.fetch_source(
        "hugging-face-blog", {"etag": "old"}, now=NOW, transport=transport(many)
    )
    assert result.receipt["status"] == "partial" and result.receipt["truncated"]
    assert len(result.items) == 25 and result.validators == {"etag": "old"}
    assert result.receipt["successful_window"] is None
    late = m.fetch_source(
        "arxiv-cs-ai", now=NOW, transport=transport(RSS, url=m.SOURCES["arxiv-cs-ai"].url)
    )
    assert len(late.items) == 1
    old = m.fetch_source(
        "hugging-face-blog",
        now=NOW,
        transport=transport(BLOG.replace(b"02 Nov 2026", b"02 Nov 2025")),
    )
    assert old.items == [] and old.receipt["status"] == "success"
    assert old.receipt["successful_window"] is None


def test_not_modified_does_not_claim_history_or_drop_validators() -> None:
    result = m.fetch_source(
        "hugging-face-blog", {"etag": "old"}, now=NOW, transport=transport(status=304)
    )
    assert result.items == [] and result.validators == {"etag": "old"}
    assert result.receipt["status"] == "not_modified"
    assert result.receipt["successful_window"] is None
    fresh = m.fetch_source("hugging-face-blog", now=NOW, transport=transport(status=304))
    assert fresh.receipt["error"] == "unexpected_not_modified"


@pytest.mark.parametrize(
    "status,headers,error",
    [
        (429, {"Retry-After": "60"}, "source_rate_limited"),
        (503, {}, "http_503"),
        (200, {"Content-Type": "text/html"}, "unexpected_content_type"),
    ],
)
def test_failure_never_advances_validators(
    status: int, headers: dict[str, str], error: str
) -> None:
    result = m.fetch_source(
        "hugging-face-blog",
        {"etag": "old"},
        now=NOW,
        transport=transport(status=status, headers=headers),
    )
    assert result.items == [] and result.validators == {"etag": "old"}
    assert result.receipt["error"] == error
    assert result.receipt["successful_window"] is None
    if status == 429:
        assert result.receipt["retry_after"] == "2026-11-02T16:01:00Z"


def test_network_errors_and_bad_resolved_url_are_safe_failures() -> None:
    def broken(url: str, headers: dict[str, str]) -> m.HttpResponse:
        raise OSError("private connection details")

    result = m.fetch_source("hugging-face-blog", now=NOW, transport=broken)
    assert result.receipt["error"] == "source_unavailable"
    bad = m.fetch_source(
        "hugging-face-blog", now=NOW, transport=transport(url="https://evil.com/feed")
    )
    assert bad.receipt["error"] == "source_not_allowed"


@pytest.mark.parametrize(
    "kwargs", [{"max_items": 0}, {"max_items": 26}, {"lookback_days": 0}, {"lookback_days": 32}]
)
def test_invalid_fetch_bounds(kwargs: dict[str, int]) -> None:
    with pytest.raises(m.IntakeError, match="invalid_fetch_bounds"):
        m.fetch_source("hugging-face-blog", **kwargs)


def test_invalid_validator_and_naive_clock_refused() -> None:
    with pytest.raises(m.IntakeError, match="invalid_validator"):
        m.fetch_source("google-research", {"etag": "bad\r\nInjected: yes"}, now=NOW)
    with pytest.raises(m.IntakeError, match="timezone_required"):
        m.normalize_manual("10.1234/test", now=datetime(2026, 11, 2))


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "http://127.0.0.1/x",
        "https://169.254.169.254/latest",
        "http://localhost/",
        "http://example.local/",
        "http://user:secret@example.com/",
        "https://example.com:444/",
        "https://example.com:bad/",
        "https://example.com/\nx",
        "https://example.com/\\evil",
        "https://example.test/",
        "https://x/",
        "https://" + "x" * 4096,
    ],
)
def test_manual_unsafe_urls_refused(value: str) -> None:
    with pytest.raises(m.IntakeError, match="unsafe"):
        m.normalize_manual(value, now=NOW)


def test_manual_identity_urls_versions_and_tracking() -> None:
    arxiv = m.normalize_manual("arXiv:2611.00001v3", now=NOW)
    assert arxiv["work_id"] == "arxiv:2611.00001" and arxiv["version_id"].endswith(":v3")
    doi = m.normalize_manual("10.1234/TeSt", now=NOW)
    assert doi["work_id"] == "doi:10.1234/test"
    url = m.normalize_manual("https://example.com/post?utm_source=x&b=2&a=1#section", now=NOW)
    assert url["url"] == "https://example.com/post?a=1&b=2"
    assert url["access_state"] == "metadata" and not url["abstract"]
    assert url["limitations"]
    assert (
        m.normalize_manual("http://arxiv.org/abs/2611.00001", now=NOW)["version_label"]
        == "unversioned"
    )
    with pytest.raises(m.IntakeError, match="missing_arxiv_identifier"):
        m.normalize_manual("https://arxiv.org/abs/no", now=NOW)


def test_date_semantics_and_html_are_bounded() -> None:
    assert m._date("2026-11-02") == ("2026-11-02T00:00:00Z", "date")
    for raw in ("", "yesterday", "2026-11-02T10:00:00", "Mon, 02 Nov 2026 10:00:00"):
        assert m._date(raw) == (None, None)
    assert m._retry_after(None, NOW) is None
    assert m._retry_after("Mon, 02 Nov 2026 17:00:00 GMT", NOW) == "2026-11-02T17:00:00Z"
    assert m._retry_after("nonsense", NOW) is None
    assert (
        m.plain_text(
            "<style>bad</style><div>Safe<br>text</div><iframe>secret</iframe><p>more</p>", 9
        )
        == "Safe text"
    )


def test_public_address_policy_rejects_any_private_dns_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        m.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    assert m._public_addresses("example.com") == ["93.184.216.34"]
    monkeypatch.setattr(
        m.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443)), (2, 1, 6, "", ("93.184.216.34", 443))],
    )
    with pytest.raises(m.IntakeError, match="unsafe_dns_address"):
        m._public_addresses("example.com")


def test_cross_process_governor_uses_shared_arxiv_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(m.tempfile, "gettempdir", lambda: str(tmp_path))
    sleeps: list[float] = []
    monkeypatch.setattr(m.time, "sleep", sleeps.append)
    monkeypatch.setattr(m.time, "time", lambda: 100.0)
    with m._rate_slot("rss.arxiv.org"):
        pass
    with m._rate_slot("export.arxiv.org"):
        pass
    with m._rate_slot("huggingface.co"):
        pass
    assert len(list(tmp_path.iterdir())) == 2
    assert sleeps == [0.0, pytest.approx(3.1), 0.0]


def request_fake(monkeypatch: pytest.MonkeyPatch, responses: list[MagicMock]) -> list[MagicMock]:
    pools: list[MagicMock] = []
    monkeypatch.setattr(m, "_public_addresses", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(m, "_rate_slot", lambda host: contextlib.nullcontext())

    def pool(*args: Any, **kwargs: Any) -> MagicMock:
        assert args == ("93.184.216.34",)
        assert kwargs["assert_hostname"] in m.ALLOWED_FETCH_HOSTS
        result = MagicMock()
        result.urlopen.return_value = responses.pop(0)
        pools.append(result)
        return result

    monkeypatch.setattr(m.urllib3, "HTTPSConnectionPool", pool)
    return pools


def response(
    status: int = 200, headers: dict[str, str] | None = None, body: bytes = BLOG
) -> MagicMock:
    result = MagicMock(status=status, headers=headers or {})
    result.read.side_effect = [body, b""]
    return result


def test_pinned_tls_and_each_redirect_is_counted_and_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = response(302, {"Location": "/blog/new-feed.xml"}), response()
    pools = request_fake(monkeypatch, [first, second])
    result = m._request(m.SOURCES["hugging-face-blog"].url, {"User-Agent": "test"})
    assert result.request_count == 2 and result.url.endswith("new-feed.xml")
    for pool in pools:
        assert pool.urlopen.call_args.kwargs["redirect"] is False
        assert pool.urlopen.call_args.kwargs["retries"] is False
        assert pool.urlopen.call_args.kwargs["headers"]["Host"] == "huggingface.co"
        pool.close.assert_called_once()
    first.close.assert_called_once()
    second.close.assert_called_once()


@pytest.mark.parametrize(
    "headers,error",
    [
        ({"Location": "https://127.0.0.1/x"}, "unsafe_address"),
        ({"Location": "https://evil.com/feed"}, "source_not_allowed"),
        ({"Location": "https://research.google/blog/rss/"}, "source_redirect_host_mismatch"),
        ({}, "redirect_missing_location"),
    ],
)
def test_redirect_policy_before_next_connection(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str], error: str
) -> None:
    pools = request_fake(monkeypatch, [response(302, headers)])
    with pytest.raises(m.IntakeError, match=error) as caught:
        m._request(m.SOURCES["hugging-face-blog"].url, {})
    assert caught.value.request_count == 1 and len(pools) == 1


@pytest.mark.parametrize(
    "headers,body,error",
    [
        ({"Content-Encoding": "gzip"}, b"", "unsupported_content_encoding"),
        ({"Content-Length": str(m.MAX_BYTES + 1)}, b"", "response_too_large"),
        ({"Content-Length": "wat"}, b"", "response_too_large"),
        ({}, b"x" * (m.MAX_BYTES + 1), "response_too_large"),
    ],
)
def test_transport_bounds(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str], body: bytes, error: str
) -> None:
    request_fake(monkeypatch, [response(headers=headers, body=body)])
    with pytest.raises(m.IntakeError, match=error):
        m._request(m.SOURCES["google-research"].url, {})


def test_transport_redirect_limit_deadline_and_failure_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_fake(monkeypatch, [response(302, {"Location": "/another"}) for _ in range(4)])
    with pytest.raises(m.IntakeError, match="redirect_limit") as caught:
        m._request(m.SOURCES["google-research"].url, {})
    assert caught.value.request_count == 4
    request_fake(monkeypatch, [response()])
    ticks = iter([0.0, 31.0])
    monkeypatch.setattr(m.time, "monotonic", lambda: next(ticks))
    with pytest.raises(m.IntakeError, match="response_deadline"):
        m._request(m.SOURCES["google-research"].url, {})


def test_dns_failure_records_zero_actual_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_dns(host: str) -> list[str]:
        raise OSError("DNS unavailable")

    monkeypatch.setattr(m, "_public_addresses", no_dns)
    result = m.fetch_source("google-research", now=NOW)
    assert result.receipt["status"] == "failed"
    assert result.receipt["error"] == "source_unavailable"
    assert result.receipt["request_count"] == 0


def test_transport_network_failure_closes_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    pools = request_fake(monkeypatch, [response()])
    # Fail during reading so pool and response ownership are both exercised.
    resp = response()
    resp.read.side_effect = urllib3.exceptions.ReadTimeoutError(None, "/", "timed out")
    pools = request_fake(monkeypatch, [resp])
    result = m.fetch_source("google-research", now=NOW)
    assert result.receipt["error"] == "source_unavailable" and result.receipt["request_count"] == 1
    assert len(pools) == 1
    pools[0].close.assert_called_once()
    resp.close.assert_called_once()


def test_resolved_connector_cannot_be_silently_substituted() -> None:
    result = m.fetch_source(
        "hugging-face-blog", now=NOW, transport=transport(url=m.SOURCES["google-research"].url)
    )
    assert result.receipt["status"] == "failed"
    assert result.receipt["error"] == "source_redirect_host_mismatch"
    assert result.items == []


def test_retry_after_seven_day_delay_is_preserved_exactly() -> None:
    assert m._retry_after("604800", NOW) == "2026-11-09T16:00:00Z"
    assert m._retry_after(" 000604800 ", NOW) == "2026-11-09T16:00:00Z"
    assert m._retry_after("0", NOW) == "2026-11-02T16:00:00Z"
    result = m.fetch_source(
        "hugging-face-blog",
        {"etag": "old"},
        now=NOW,
        transport=transport(status=429, headers={"Retry-After": "604800"}),
    )
    assert result.receipt["retry_after"] == "2026-11-09T16:00:00Z"
    assert result.receipt["status"] == "rate_limited"
    assert result.validators == {"etag": "old"} and result.items == []


@pytest.mark.parametrize("raw", ["999999999999999", "9" * 5000])
def test_unrepresentable_retry_after_quarantines_instead_of_retrying_early(raw: str) -> None:
    with pytest.raises(m.IntakeError, match="retry_after_unrepresentable"):
        m._retry_after(raw, NOW)
    result = m.fetch_source(
        "hugging-face-blog",
        {"etag": "old"},
        now=NOW,
        transport=transport(status=429, headers={"Retry-After": raw}),
    )
    assert result.receipt["status"] == "quarantined"
    assert result.receipt["quarantined"] is True
    assert result.receipt["error"] == "retry_after_unrepresentable"
    assert result.receipt["retry_after"] == "9999-12-31T23:59:59.999999Z"
    assert datetime.fromisoformat(result.receipt["retry_after"]) > NOW
    assert result.receipt["successful_window"] is None
    assert result.validators == {"etag": "old"} and result.items == []


def test_retry_after_datetime_horizon_is_checked_before_arithmetic() -> None:
    near_horizon = datetime(9999, 12, 31, 23, 59, 58, tzinfo=UTC)
    assert m._retry_after("1", near_horizon) == "9999-12-31T23:59:59Z"
    with pytest.raises(m.IntakeError, match="retry_after_unrepresentable"):
        m._retry_after("2", near_horizon)
