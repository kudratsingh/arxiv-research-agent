"""PDF download and full-text extraction using PyMuPDF.

Downloads a PDF from a URL, extracts its text, and caches both the raw
PDF and the extracted text on disk so repeated calls don't re-download
or re-parse. Returns "" on any failure — callers should treat that as
a graceful signal to fall back (e.g. to the abstract).
"""

import hashlib
import re
from pathlib import Path

import fitz
import requests

from src.observability import get_logger
from src.tools.http_session import build_retrying_session

DEFAULT_CACHE_DIR = Path(".cache/pdfs")
DOWNLOAD_TIMEOUT_SEC = 60

log = get_logger(__name__)


def _cache_key(pdf_url: str) -> str:
    """Derive a stable filesystem-safe key for a PDF URL.

    Prefers the arXiv ID embedded in the URL (e.g. "2311.09000" or
    "2311.09000v2"); falls back to a short SHA1 for non-arXiv URLs.
    """
    match = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", pdf_url)
    if match:
        return match.group(1)
    return hashlib.sha1(pdf_url.encode("utf-8")).hexdigest()[:16]


def _download_pdf(pdf_url: str, dest: Path) -> bool:
    """Download a PDF to `dest`. Returns True on success.

    Uses a retrying session so transient 429s from arXiv's PDF host
    don't drop us into abstract-only mode. A hard failure (bad URL,
    non-PDF body, extraction throw) still returns False and the reader
    falls back gracefully.
    """
    session = build_retrying_session()
    try:
        resp = session.get(
            pdf_url, timeout=DOWNLOAD_TIMEOUT_SEC, allow_redirects=True
        )
    except (requests.RequestException, OSError) as exc:
        log.warning(
            "pdf_download_failed",
            extra={"pdf_url": pdf_url, "error": str(exc)},
        )
        return False

    if resp.status_code != 200:
        log.warning(
            "pdf_download_http_error",
            extra={"pdf_url": pdf_url, "status": resp.status_code},
        )
        return False

    if not resp.content.startswith(b"%PDF-"):
        log.warning(
            "pdf_download_not_a_pdf",
            extra={"pdf_url": pdf_url},
        )
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return True


def _extract_text(pdf_path: Path) -> str:
    """Extract concatenated page text from a local PDF file."""
    with fitz.open(pdf_path) as doc:
        return "\n".join(page.get_text() for page in doc)


def parse_pdf(pdf_url: str, cache_dir: Path | str = DEFAULT_CACHE_DIR) -> str:
    """Fetch, cache, and extract text from a PDF at `pdf_url`.

    Cache layout under `cache_dir`:
        <key>.pdf   the raw downloaded PDF
        <key>.txt   the extracted text (returned on subsequent calls)

    Args:
        pdf_url: HTTP(S) URL of the PDF to fetch.
        cache_dir: Directory used to cache downloads and extractions.

    Returns:
        The extracted text, or "" if download or extraction failed.
    """
    if not pdf_url:
        return ""

    cache_dir = Path(cache_dir)
    key = _cache_key(pdf_url)
    txt_path = cache_dir / f"{key}.txt"
    pdf_path = cache_dir / f"{key}.pdf"

    if txt_path.exists():
        return txt_path.read_text(encoding="utf-8")

    if not pdf_path.exists() and not _download_pdf(pdf_url, pdf_path):
        return ""

    try:
        text = _extract_text(pdf_path)
    except (RuntimeError, OSError, ValueError) as exc:
        log.warning(
            "pdf_extraction_failed",
            extra={"pdf_path": str(pdf_path), "error": str(exc)},
        )
        return ""

    txt_path.write_text(text, encoding="utf-8")
    return text
