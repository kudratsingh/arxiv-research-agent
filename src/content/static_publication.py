"""Build the credential-free WO-W16 static reading-path publication.

Production mode is intentionally impossible until W-OD-2/3/4 are resolved:
the flagship manifest must be published, every visible paper must have a
reviewed briefing, and an owner-selected external waitlist URL must be passed.
Preview mode renders the sequence for local review with ``noindex`` and no
collection mechanism. Both modes produce plain HTML/CSS with no JavaScript,
product API route, credential, analytics, or tracking surface.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

from src.content.loader import LoadedPath, load_path_dir
from src.content.schema import Briefing, Entry

FLAGSHIP_PATH_ID: Final = "reading-first-papers"
REPOSITORY_URL: Final = "https://github.com/kudratsingh/arxiv-research-agent"

_ARXIV_ABS = re.compile(r"^https://arxiv\.org/abs/")
_FORBIDDEN_ARTIFACT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"anthropic_api_key",
        r"authorization\s*:",
        r"bearer\s+[a-z0-9]",
        r"/api/",
        r"localhost",
        r"127\.0\.0\.1",
        r"<script\b",
        r"google-analytics",
        r"segment\.com",
    )
)

_CSS = """\
:root {
  --ink: #13263d;
  --cobalt: #2457e6;
  --mist: #eaf0fa;
  --paper: #fbfcfe;
  --amber: #e8a317;
  --muted: #5c6b7c;
  --line: #c9d5e7;
  color-scheme: light;
}
* { box-sizing: border-box; }
html { background: var(--paper); color: var(--ink); scroll-behavior: smooth; }
body { margin: 0; font-family: "Avenir Next", Avenir, "Segoe UI", sans-serif; line-height: 1.6; }
a { color: var(--cobalt); text-underline-offset: .2em; }
a:hover { text-decoration-thickness: .14em; }
a:focus-visible { outline: 3px solid var(--amber); outline-offset: 4px; border-radius: 2px; }
.shell { width: min(72rem, calc(100% - 2rem)); margin-inline: auto; }
.masthead { display: flex; justify-content: space-between; align-items: center; padding-block: 1.2rem; border-bottom: 1px solid var(--line); }
.wordmark { color: var(--ink); font: 600 .78rem/1.2 "SFMono-Regular", Consolas, monospace; letter-spacing: .08em; text-transform: uppercase; text-decoration: none; }
.state { font: 500 .68rem/1.2 "SFMono-Regular", Consolas, monospace; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.review-hold { border-block: 1px solid #e9c46a; background: #fff8df; color: #5d4300; padding: .8rem 1rem; font-size: .88rem; }
.hero { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(16rem, .7fr); gap: clamp(2rem, 7vw, 7rem); padding-block: clamp(4rem, 10vw, 8rem); }
.eyebrow { color: var(--cobalt); font: 500 .72rem/1.3 "SFMono-Regular", Consolas, monospace; letter-spacing: .12em; text-transform: uppercase; }
h1, h2, h3 { font-family: "Iowan Old Style", "Palatino Linotype", Palatino, serif; font-weight: 600; letter-spacing: -.025em; }
h1 { max-width: 13ch; margin: .65rem 0 1.25rem; font-size: clamp(3.1rem, 8vw, 6.8rem); line-height: .94; }
.lede { max-width: 42rem; margin: 0; color: #344960; font-size: clamp(1.08rem, 2vw, 1.35rem); }
.thesis { align-self: end; border-left: 4px solid var(--amber); padding-left: 1.25rem; }
.thesis dt { color: var(--muted); font: 500 .67rem/1.2 "SFMono-Regular", Consolas, monospace; letter-spacing: .09em; text-transform: uppercase; }
.thesis dd { margin: .45rem 0 1.4rem; font-family: "Iowan Old Style", "Palatino Linotype", Palatino, serif; font-size: 1.08rem; line-height: 1.45; }
.sequence-head { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; padding-block: 1.5rem; border-block: 1px solid var(--line); }
.sequence-head h2 { margin: 0; font-size: clamp(1.8rem, 4vw, 3rem); }
.sequence-head p { margin: 0; color: var(--muted); font-size: .9rem; }
.spine { position: relative; list-style: none; margin: 0; padding: 3rem 0 4rem 4.25rem; }
.spine::before { content: ""; position: absolute; left: 1.28rem; top: 3.2rem; bottom: 4.2rem; width: 2px; background: linear-gradient(var(--cobalt), var(--amber)); }
.paper-card { position: relative; display: grid; grid-template-columns: minmax(0, 1fr) minmax(14rem, .36fr); gap: 2rem; padding: 0 0 3.5rem; }
.position { position: absolute; left: -4.25rem; top: .05rem; display: grid; width: 2.6rem; height: 2.6rem; place-items: center; border: 2px solid var(--cobalt); border-radius: 50%; background: var(--paper); color: var(--cobalt); font: 600 .72rem/1 "SFMono-Regular", Consolas, monospace; }
.paper-card h3 { margin: 0 0 .45rem; font-size: clamp(1.65rem, 3vw, 2.5rem); line-height: 1.08; }
.byline, .attribution { color: var(--muted); font-size: .83rem; }
.rationale { max-width: 44rem; margin: 1rem 0 0; }
.paper-side { align-self: start; padding: 1rem; border: 1px solid var(--line); background: #fff; }
.paper-side dt { color: var(--muted); font: 500 .64rem/1.2 "SFMono-Regular", Consolas, monospace; letter-spacing: .08em; text-transform: uppercase; }
.paper-side dd { margin: .3rem 0 1rem; font-size: .88rem; }
.terms { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: 1rem; }
.term { padding: .28rem .55rem; border-radius: 999px; background: var(--mist); color: #29445f; font-size: .72rem; }
.actions { display: flex; flex-wrap: wrap; gap: .7rem; margin-top: 1.2rem; }
.button { display: inline-flex; align-items: center; min-height: 2.7rem; padding: .55rem .85rem; border: 1px solid var(--cobalt); color: var(--cobalt); font-weight: 600; text-decoration: none; }
.button.primary { background: var(--cobalt); color: #fff; }
.button.disabled { border-color: var(--line); color: var(--muted); cursor: not-allowed; }
.mentor { margin-block: 1rem 5rem; padding: clamp(2rem, 6vw, 5rem); background: var(--ink); color: #f7f9fc; }
.mentor h2 { max-width: 16ch; margin: 0 0 1rem; font-size: clamp(2rem, 5vw, 4.5rem); line-height: 1; }
.mentor p { max-width: 42rem; color: #c8d7e7; }
.briefing-shell { width: min(48rem, calc(100% - 2rem)); margin: 4rem auto 7rem; }
.briefing-shell h1 { max-width: none; font-size: clamp(2.5rem, 7vw, 5rem); }
.briefing-label { padding: 1rem; border-left: 4px solid var(--amber); background: #fff8df; }
.briefing-copy { margin-top: 3rem; }
.briefing-copy h2 { margin-top: 2.5rem; font-size: 2rem; }
.briefing-copy blockquote { margin: 1.5rem 0; padding-left: 1.25rem; border-left: 3px solid var(--cobalt); color: #344960; }
.briefing-copy table { width: 100%; border-collapse: collapse; font-size: .9rem; }
.briefing-copy th, .briefing-copy td { padding: .65rem; border: 1px solid var(--line); text-align: left; vertical-align: top; }
.footer { padding-block: 2rem; border-top: 1px solid var(--line); color: var(--muted); font-size: .78rem; }
@media (max-width: 740px) {
  .hero, .paper-card { grid-template-columns: 1fr; }
  .hero { padding-block: 3.5rem; }
  .spine { padding-left: 3.4rem; }
  .spine::before { left: 1rem; }
  .position { left: -3.4rem; width: 2.1rem; height: 2.1rem; }
  .sequence-head { display: block; }
}
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
"""


def _safe_waitlist_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme == "mailto" and parsed.path:
        return value
    if parsed.scheme == "https" and parsed.netloc:
        return value
    raise ValueError("waitlist URL must be an https form or mailto address")


def _production_entries(path: LoadedPath) -> list[Entry]:
    manifest = path.manifest
    if manifest.path_id != FLAGSHIP_PATH_ID or manifest.fixture:
        raise ValueError("production publication requires the non-fixture flagship path")
    if manifest.status != "published":
        raise ValueError(
            f"flagship path is {manifest.status!r}, not 'published'; W-OD-2/3 remain open"
        )
    entries = manifest.servable_entries
    if len(entries) != len(manifest.entries):
        raise ValueError("production publication refuses proposed, stale, or rejected entries")
    for entry in entries:
        if entry.kind == "paper" and path.servable_briefing(entry) is None:
            raise ValueError(f"reviewed briefing missing for {entry.resource_id}")
    return entries


def _inline(value: str) -> str:
    escaped = html.escape(value)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(
        r"&lt;(https://[^&]+?)&gt;",
        lambda match: (
            f'<a href="{html.escape(match.group(1), quote=True)}">{html.escape(match.group(1))}</a>'
        ),
        escaped,
    )
    return escaped


def _briefing_html(briefing: Briefing) -> str:
    """Render the bounded briefing vocabulary without allowing raw HTML."""
    lines = briefing.body.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line or line == "---":
            index += 1
            continue
        if line.startswith("## "):
            output.append(f"<h2>{_inline(line[3:])}</h2>")
            index += 1
            continue
        if line.startswith("> "):
            quoted: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quoted.append(lines[index].strip().lstrip(">").strip())
                index += 1
            output.append(f"<blockquote><p>{_inline(' '.join(quoted))}</p></blockquote>")
            continue
        if line.startswith("- "):
            items: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                items.append(lines[index].strip()[2:])
                index += 1
            output.append("<ul>" + "".join(f"<li>{_inline(item)}</li>" for item in items) + "</ul>")
            continue
        if line.startswith("|") and index + 1 < len(lines):
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]+", cell) for cell in cells):
                    rows.append(cells)
                index += 1
            if rows:
                head, *body = rows
                output.append(
                    "<table><thead><tr>"
                    + "".join(f"<th>{_inline(cell)}</th>" for cell in head)
                    + "</tr></thead><tbody>"
                    + "".join(
                        "<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>"
                        for row in body
                    )
                    + "</tbody></table>"
                )
            continue
        paragraph = [line]
        index += 1
        while (
            index < len(lines)
            and lines[index].strip()
            and not re.match(r"^(## |> |- |\|)", lines[index].strip())
        ):
            paragraph.append(lines[index].strip())
            index += 1
        output.append(f"<p>{_inline(' '.join(paragraph))}</p>")
    return "\n".join(output)


def _entry_card(entry: Entry, briefing: Briefing | None, *, preview: bool) -> str:
    authors = ", ".join(entry.authors[:3])
    if entry.author_count > 3:
        authors += f" + {entry.author_count - 3} more"
    terms = "".join(f'<span class="term">{html.escape(term)}</span>' for term in entry.vocabulary)
    companion = (
        f'<a class="button" href="briefings/{entry.position:02d}.html">Read the companion</a>'
        if briefing is not None
        else '<span class="button disabled">Companion awaiting review</span>'
    )
    status = "Review preview" if preview else "Reviewed"
    return f"""\
<li class="paper-card">
  <span class="position">{entry.position:02d}</span>
  <div>
    <h3>{html.escape(entry.title)}</h3>
    <div class="byline">{html.escape(authors)} · {entry.year}</div>
    <p class="rationale">{html.escape(entry.rationale)}</p>
    <div class="terms">{terms}</div>
    <div class="actions">
      {companion}
      <a class="button primary" href="{html.escape(entry.canonical_url, quote=True)}">Open the source ↗</a>
    </div>
  </div>
  <dl class="paper-side">
    <dt>Publication state</dt><dd>{status}</dd>
    <dt>Reading estimate</dt><dd>{entry.est_minutes} minutes across sessions</dd>
    <dt>Attribution</dt><dd>{html.escape(entry.attribution)}</dd>
  </dl>
</li>"""


def _page(title: str, body: str, *, preview: bool) -> str:
    robots = '<meta name="robots" content="noindex,nofollow">' if preview else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  {robots}
  <title>{html.escape(title)}</title>
  <meta name="description" content="A guided sequence through the papers that built modern language models.">
  <link rel="stylesheet" href="{("../" if "briefing" in body else "")}style.css">
</head>
<body>{body}</body>
</html>
"""


def _index_body(
    path: LoadedPath,
    entries: Sequence[Entry],
    *,
    preview: bool,
    waitlist_url: str | None,
) -> str:
    manifest = path.manifest
    cards = "\n".join(
        _entry_card(entry, path.servable_briefing(entry), preview=preview) for entry in entries
    )
    hold = (
        '<div class="review-hold">Review preview · not published · no signup data is collected. '
        "Briefings and licensing posture still await owner approval.</div>"
        if preview
        else ""
    )
    cta = (
        '<span class="button disabled">Waitlist opens after owner approval</span>'
        if waitlist_url is None
        else f'<a class="button primary" href="{html.escape(waitlist_url, quote=True)}">Join the waitlist ↗</a>'
    )
    return f"""\
{hold}
<header class="masthead shell">
  <a class="wordmark" href="{REPOSITORY_URL}">arXiv research agent</a>
  <span class="state">Curated argument · version {manifest.version}</span>
</header>
<main>
  <section class="hero shell">
    <div><div class="eyebrow">A path through language-model history</div>
      <h1>{len(entries)} sources. One argument.</h1>
      <p class="lede">{html.escape(manifest.goal)}</p>
    </div>
    <dl class="thesis">
      <dt>How to use it</dt><dd>Follow the sequence. Each source answers a problem the previous source leaves open.</dd>
      <dt>What the mentor adds</dt><dd>A time-bounded plan, vocabulary before notation, and an explain-back grounded in your own words.</dd>
    </dl>
  </section>
  <section class="shell" aria-labelledby="sequence-title">
    <div class="sequence-head"><h2 id="sequence-title">The argument spine</h2><p>Source pages only · no PDFs are re-hosted</p></div>
    <ol class="spine">{cards}</ol>
  </section>
  <section class="mentor shell">
    <div class="eyebrow">The mentor vision</div>
    <h2>Read less. Notice more.</h2>
    <p>The finished mentor remembers the thread, cuts the day to the minutes you actually have, and asks you to explain the paper back. It records evidence, never a fictional mastery percentage.</p>
    <div class="actions">{cta}<a class="button" href="{REPOSITORY_URL}">Inspect the open-source build ↗</a></div>
  </section>
</main>
<footer class="footer shell">Link-out only. Metadata and attribution stay beside every source. No analytics or tracking scripts.</footer>"""


def build_publication(
    path_dir: Path,
    output_dir: Path,
    *,
    preview: bool = False,
    waitlist_url: str | None = None,
) -> list[Path]:
    """Build an isolated artifact and return every emitted file."""
    path = load_path_dir(path_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output directory must be absent or empty: {output_dir}")
    if preview:
        entries = list(path.manifest.entries)
        safe_waitlist = None
    else:
        entries = _production_entries(path)
        if waitlist_url is None:
            raise ValueError("production publication requires the W-OD-4 waitlist URL")
        safe_waitlist = _safe_waitlist_url(waitlist_url)

    output_dir.mkdir(parents=True, exist_ok=True)
    briefing_dir = output_dir / "briefings"
    briefing_dir.mkdir()
    emitted = [output_dir / "index.html", output_dir / "style.css"]
    emitted[0].write_text(
        _page(
            path.manifest.title,
            _index_body(path, entries, preview=preview, waitlist_url=safe_waitlist),
            preview=preview,
        ),
        encoding="utf-8",
    )
    emitted[1].write_text(_CSS, encoding="utf-8")
    for entry in entries:
        briefing = path.servable_briefing(entry)
        if briefing is None:
            continue
        target = briefing_dir / f"{entry.position:02d}.html"
        body = f"""\
<header class="masthead shell"><a class="wordmark" href="../index.html">← The argument spine</a><span class="state">{html.escape(entry.attribution)}</span></header>
<main class="briefing-shell"><div class="eyebrow">Reading companion · source {entry.position:02d}</div><h1>{html.escape(entry.title)}</h1>
<p class="briefing-label">{html.escape(briefing.header.label)}</p>
<article class="briefing-copy">{_briefing_html(briefing)}</article>
<div class="actions"><a class="button primary" href="{html.escape(entry.canonical_url, quote=True)}">Open the source ↗</a></div></main>"""
        target.write_text(_page(entry.title, body, preview=preview), encoding="utf-8")
        emitted.append(target)

    metadata = output_dir / "publication.json"
    metadata.write_text(
        json.dumps(
            {
                "path_id": path.path_id,
                "manifest_version": path.manifest.version,
                "mode": "preview" if preview else "production",
                "entry_count": len(entries),
                "waitlist": "absent" if safe_waitlist is None else "external",
                "tracking": "none",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    emitted.append(metadata)
    validate_artifact(output_dir, entries=entries, production=not preview)
    return emitted


def validate_artifact(output_dir: Path, *, entries: Iterable[Entry], production: bool) -> None:
    """Assert licensing and credential-boundary rules on built bytes."""
    files = sorted(path for path in output_dir.rglob("*") if path.is_file())
    if not files or not (output_dir / "index.html").is_file():
        raise ValueError("static artifact is missing index.html")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for pattern in _FORBIDDEN_ARTIFACT_PATTERNS:
        if pattern.search(combined):
            raise ValueError(f"static artifact contains forbidden pattern {pattern.pattern!r}")
    for entry in entries:
        if entry.kind == "paper" and not _ARXIV_ABS.match(entry.canonical_url):
            raise ValueError(f"paper does not link to an arXiv abs page: {entry.resource_id}")
        if entry.canonical_url not in combined:
            raise ValueError(f"built artifact omits canonical link for {entry.resource_id}")
        if entry.attribution not in combined:
            raise ValueError(f"built artifact omits attribution for {entry.resource_id}")
    if production and "noindex,nofollow" in combined:
        raise ValueError("production artifact may not carry preview noindex metadata")
    if not production and "noindex,nofollow" not in combined:
        raise ValueError("preview artifact must be noindex")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the WO-W16 static path")
    parser.add_argument(
        "--path-dir",
        type=Path,
        default=Path("content/paths/reading-first-papers"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--waitlist-url")
    args = parser.parse_args(argv)
    build_publication(
        args.path_dir,
        args.output,
        preview=args.preview,
        waitlist_url=args.waitlist_url,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI wiring
    raise SystemExit(main())
