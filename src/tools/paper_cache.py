"""PaperCache: pluggable extracted-text cache used by `pdf_parser`.

Two implementations, one Protocol:

- `DiskPaperCache`  — Sprint 1 behavior. Writes `<key>.pdf` +
  `<key>.txt` under `.cache/pdfs/`. Byte-identical to the previous
  in-file logic in `pdf_parser.py`; extracted here so the Postgres
  variant is a swap, not a rewrite.
- `PostgresPaperCache` — `paper_cache` table via `postgres_pool`.
  Full text is stored server-side; multiple containers share the
  cache across horizontal-scale API workers, and cold starts don't
  re-download PDFs that another worker already fetched.

Selection is driven by `settings.paper_cache` in `get_paper_cache()`.

Design in ADR 0028.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from src.config import settings
from src.observability import get_logger

log = get_logger(__name__)

DEFAULT_CACHE_DIR = Path(".cache/pdfs")


class PaperCache(Protocol):
    """Structural type for extracted-text caches.

    Cache misses return `None`; downstream callers translate that
    into "download and parse then put". `put_text` is idempotent —
    a repeat write is treated as an update.
    """

    def get_text(self, paper_key: str) -> str | None: ...

    def put_text(self, paper_key: str, pdf_url: str, full_text: str) -> None: ...


# ---------------------------------------------------------------------
# Disk implementation — Sprint 1 behavior, extracted verbatim.
# ---------------------------------------------------------------------


class DiskPaperCache:
    """Filesystem cache under `cache_dir`.

    Layout mirrors the pre-Sprint-4 `.cache/pdfs/` convention so a
    running deployment can be flipped between disk and Postgres
    without wiping the local cache. The raw PDF still lives on disk
    (the parser writes it separately); only the extracted text goes
    through this cache.
    """

    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE_DIR) -> None:
        self._cache_dir = Path(cache_dir)

    def get_text(self, paper_key: str) -> str | None:
        path = self._cache_dir / f"{paper_key}.txt"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def put_text(self, paper_key: str, pdf_url: str, full_text: str) -> None:
        # `pdf_url` is ignored by the disk implementation — the key
        # already encodes the URL identity per `_cache_key`. It's
        # part of the Protocol so the Postgres variant can persist
        # the URL for auditing without a wider signature change.
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        (self._cache_dir / f"{paper_key}.txt").write_text(
            full_text, encoding="utf-8"
        )


# ---------------------------------------------------------------------
# Postgres implementation — shared cache across horizontal API workers.
# ---------------------------------------------------------------------


class PostgresPaperCache:
    """`paper_cache` table via the shared connection pool.

    Read path is a single indexed lookup on `paper_key`; write path
    is an UPSERT so repeat puts are idempotent. Errors are caught
    at the pdf_parser boundary — the parser logs and falls back to
    a fresh download if this raises.
    """

    def get_text(self, paper_key: str) -> str | None:
        from src.tools.postgres_pool import _connection, init_schema

        init_schema()
        with _connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT full_text FROM paper_cache WHERE paper_key = %s",
                (paper_key,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return str(row[0])

    def put_text(self, paper_key: str, pdf_url: str, full_text: str) -> None:
        from src.tools.postgres_pool import _connection, init_schema

        init_schema()
        with _connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO paper_cache
                    (paper_key, pdf_url, full_text, text_length)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (paper_key) DO UPDATE SET
                    pdf_url = EXCLUDED.pdf_url,
                    full_text = EXCLUDED.full_text,
                    text_length = EXCLUDED.text_length,
                    updated_at = NOW()
                """,
                (paper_key, pdf_url, full_text, len(full_text)),
            )
            conn.commit()


# ---------------------------------------------------------------------
# Factory — the singleton entry point call sites use.
# ---------------------------------------------------------------------


_cache: PaperCache | None = None


def get_paper_cache() -> PaperCache:
    """Return the module-level singleton, selected by settings.

    Lazy so the postgres client isn't touched at import time when
    the app is running with `paper_cache=disk`. Tests reset via
    `_reset_for_test`.
    """
    global _cache
    if _cache is not None:
        return _cache

    if settings.paper_cache == "postgres":
        _cache = PostgresPaperCache()
        log.info("paper_cache_selected", extra={"impl": "postgres"})
    else:
        _cache = DiskPaperCache()
        log.info("paper_cache_selected", extra={"impl": "disk"})
    return _cache


def _reset_for_test(cache: PaperCache | None = None) -> None:
    """Test seam — inject a cache or clear the singleton."""
    global _cache
    _cache = cache
