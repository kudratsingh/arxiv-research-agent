"""Link-rot check over every URL a manifest publishes.

`02` §3.3: "Dead links in a learning path are a product-killing
experience; this must be boring and automatic." This is the boring half.
It walks every URL in every manifest — the abs page, the licence, the
Semantic Scholar link-back, the abstract's own link — and reports which
ones still resolve.

It **reports**; it does not edit. `02` §3.3 has failures transition a row
to `stale`, and in Phase L, where content lives in Postgres, that is a
write. Here content is a file in git, so the transition is a commit a
human makes after reading this report — which is also the only version
that leaves an audit trail.

Run it:

    .venv/bin/python -m src.content.linkcheck
    .venv/bin/python -m src.content.linkcheck --json > report.json

Exit codes: `0` every link resolved, `1` at least one did not, `2` the
content tree failed validation before any link was tried.

Network use is deliberately modest: one request per URL, `HEAD` first and
`GET` only where a host rejects `HEAD`, with a politeness delay between
requests to the same host. It calls no model and needs no API key.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests

from src.content.loader import LoadedPath, content_root, load_content_root
from src.content.schema import ContentValidationError
from src.observability import get_logger
from src.tools.http_session import build_retrying_session

log = get_logger(__name__)

#: Seconds between two requests to the same host. arXiv's API terms ask
#: for a delay between calls; the same courtesy is applied to every host
#: rather than special-casing one.
HOST_DELAY_SEC = 1.0

DEFAULT_TIMEOUT_SEC = 20.0

#: Sent so an operator reading their access log can tell what this is.
#: No credential, no tracking, no cookie.
USER_AGENT = (
    "arxiv-research-agent-linkcheck/1.0 "
    "(+https://github.com/kudratsingh/arxiv-research-agent)"
)

#: Statuses that mean "this host dislikes HEAD", not "this link is dead".
#: Retried once with GET before being called broken.
_HEAD_REJECTED = frozenset({400, 401, 403, 404, 405, 406, 409, 410, 501})


@dataclass(frozen=True)
class LinkTarget:
    """One URL a manifest publishes, and where it came from."""

    path_id: str
    resource_id: str
    field: str
    url: str


@dataclass(frozen=True)
class LinkResult:
    """The outcome of checking one target."""

    path_id: str
    resource_id: str
    field: str
    url: str
    ok: bool
    status_code: int | None
    method: str
    detail: str


def collect_targets(paths: Iterable[LoadedPath]) -> list[LinkTarget]:
    """Every checkable URL across `paths`, in manifest order.

    Deduplication is deliberate *not* done: the same abs page can appear
    on two paths, and a report that hides the second occurrence makes the
    reader hunt for which path is broken.
    """
    targets: list[LinkTarget] = []
    for path in paths:
        for entry in path.manifest.entries:
            targets.append(
                LinkTarget(
                    path.path_id, entry.resource_id, "canonical_url", entry.canonical_url
                )
            )
            if entry.license_url:
                targets.append(
                    LinkTarget(
                        path.path_id, entry.resource_id, "license_url", entry.license_url
                    )
                )
            if entry.sequencing.evidence_url:
                targets.append(
                    LinkTarget(
                        path.path_id,
                        entry.resource_id,
                        "sequencing.evidence_url",
                        entry.sequencing.evidence_url,
                    )
                )
            if entry.abstract is not None:
                targets.append(
                    LinkTarget(
                        path.path_id, entry.resource_id, "abstract.url", entry.abstract.url
                    )
                )
    return targets


def check_target(
    session: requests.Session, target: LinkTarget, *, timeout: float
) -> LinkResult:
    """Check one URL. Never raises — a transport failure is a result.

    Args:
        session: A session, normally from `build_retrying_session`.
        target: The URL and its provenance.
        timeout: Per-request timeout in seconds.

    Returns:
        The outcome, `ok=True` only for a final 2xx.
    """
    headers = {"User-Agent": USER_AGENT}
    method = "HEAD"
    try:
        response = session.head(
            target.url, timeout=timeout, allow_redirects=True, headers=headers
        )
        if response.status_code in _HEAD_REJECTED:
            method = "GET"
            response = session.get(
                target.url,
                timeout=timeout,
                allow_redirects=True,
                headers=headers,
                stream=True,
            )
            response.close()
    except requests.RequestException as exc:
        return LinkResult(
            path_id=target.path_id,
            resource_id=target.resource_id,
            field=target.field,
            url=target.url,
            ok=False,
            status_code=None,
            method=method,
            detail=f"{type(exc).__name__}: {exc}",
        )
    ok = 200 <= response.status_code < 300
    return LinkResult(
        path_id=target.path_id,
        resource_id=target.resource_id,
        field=target.field,
        url=target.url,
        ok=ok,
        status_code=response.status_code,
        method=method,
        detail="ok" if ok else f"HTTP {response.status_code}",
    )


def check_links(
    targets: Sequence[LinkTarget],
    *,
    session: requests.Session | None = None,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    delay_sec: float = HOST_DELAY_SEC,
) -> list[LinkResult]:
    """Check every target, pausing between requests to the same host.

    Args:
        targets: What to check.
        session: Injected for tests; defaults to the project's retrying
            session so backoff and `Retry-After` handling come free.
        timeout: Per-request timeout.
        delay_sec: Politeness delay between two requests to one host.

    Returns:
        One result per target, in input order.
    """
    http = session if session is not None else build_retrying_session()
    last_seen: dict[str, float] = defaultdict(float)
    results: list[LinkResult] = []
    for target in targets:
        host = urlsplit(target.url).netloc
        wait = delay_sec - (time.monotonic() - last_seen[host])
        if last_seen[host] and wait > 0:
            time.sleep(wait)
        results.append(check_target(http, target, timeout=timeout))
        last_seen[host] = time.monotonic()
    return results


def render_report(results: Sequence[LinkResult]) -> str:
    """A human-readable report, broken links last so they end the output."""
    lines: list[str] = []
    broken = [r for r in results if not r.ok]
    lines.append(
        f"{len(results)} link(s) checked, {len(results) - len(broken)} ok, "
        f"{len(broken)} broken"
    )
    for result in results:
        mark = "ok  " if result.ok else "FAIL"
        lines.append(
            f"  {mark} {result.status_code or '-':>3} {result.method:<4} "
            f"{result.path_id}/{result.resource_id} {result.field} "
            f"{result.url}"
        )
    if broken:
        lines.append("")
        lines.append("Broken links — 02 §3.3 transitions these to `stale`:")
        for result in broken:
            lines.append(
                f"  {result.path_id}/{result.resource_id} "
                f"{result.field}: {result.url} ({result.detail})"
            )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m src.content.linkcheck",
        description="Check every link a shipped path manifest publishes.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Content root (default: the repo-shipped content/ directory).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SEC,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=HOST_DELAY_SEC,
        help="Politeness delay between requests to the same host.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else content_root()
    try:
        paths = load_content_root(root)
    except ContentValidationError as exc:
        print(f"content validation failed before any link was checked: {exc}",
              file=sys.stderr)
        return 2

    targets = collect_targets(paths.values())
    results = check_links(targets, timeout=args.timeout, delay_sec=args.delay)
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        print(render_report(results))
    return 1 if any(not r.ok for r in results) else 0


if __name__ == "__main__":  # pragma: no cover - CLI wiring
    raise SystemExit(main())
