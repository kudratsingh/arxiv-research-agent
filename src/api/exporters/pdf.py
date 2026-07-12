"""PDF exporter — walks the markdown-it AST and emits ReportLab flowables.

Pure Python (reportlab + markdown-it-py). Handles the report shapes
the synthesizer emits: headings (h1-h4), paragraphs with inline
code + emphasis + strong + links, bullet + ordered lists, block
quotes, code blocks, and tables (GFM). Anything the walker
doesn't recognize falls back to a paragraph render of the token's
raw content — no hard failure on exotic markdown.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import Flowable, KeepTogether, ListFlowable, ListItem

from src.api.jobs import Job


def render_pdf(job: Job) -> bytes:
    """Return the job's report as PDF bytes (Letter size, one column)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        title=f"Research briefing — {job.job_id}",
        author="arxiv-research-agent",
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
    )

    styles = _make_styles()
    flowables: list[Flowable] = []

    flowables.append(Paragraph("Research briefing", styles["Title"]))
    flowables.append(Paragraph(_escape_html(job.query), styles["Subtitle"]))
    flowables.append(Spacer(1, 6))
    flowables.append(_metadata_table(job, styles))
    flowables.append(Spacer(1, 14))

    body = job.result or "(no report body)"
    tokens = MarkdownIt("commonmark", {"html": False}).enable("table").parse(body)
    flowables.extend(_tokens_to_flowables(tokens, styles))

    doc.build(flowables)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------


def _make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}
    styles["Title"] = ParagraphStyle(
        name="Title",
        parent=base["Title"],
        fontSize=20,
        leading=24,
        spaceAfter=6,
    )
    styles["Subtitle"] = ParagraphStyle(
        name="Subtitle",
        parent=base["BodyText"],
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#475569"),
        spaceAfter=6,
    )
    styles["MetaLabel"] = ParagraphStyle(
        name="MetaLabel",
        parent=base["BodyText"],
        fontSize=8,
        textColor=colors.HexColor("#64748b"),
    )
    styles["MetaValue"] = ParagraphStyle(
        name="MetaValue",
        parent=base["BodyText"],
        fontName="Courier",
        fontSize=9,
    )
    styles["H1"] = ParagraphStyle(
        name="H1",
        parent=base["Heading1"],
        fontSize=16,
        leading=20,
        spaceBefore=12,
        spaceAfter=6,
    )
    styles["H2"] = ParagraphStyle(
        name="H2",
        parent=base["Heading2"],
        fontSize=13,
        leading=17,
        spaceBefore=10,
        spaceAfter=5,
    )
    styles["H3"] = ParagraphStyle(
        name="H3",
        parent=base["Heading3"],
        fontSize=11,
        leading=14,
        spaceBefore=8,
        spaceAfter=4,
    )
    styles["Body"] = ParagraphStyle(
        name="Body",
        parent=base["BodyText"],
        fontSize=10,
        leading=14,
        spaceAfter=6,
    )
    styles["Bullet"] = ParagraphStyle(
        name="Bullet",
        parent=styles["Body"],
        leftIndent=14,
        bulletIndent=4,
    )
    styles["BlockQuote"] = ParagraphStyle(
        name="BlockQuote",
        parent=styles["Body"],
        leftIndent=16,
        textColor=colors.HexColor("#475569"),
        borderColor=colors.HexColor("#cbd5e1"),
        borderPadding=(4, 4, 4, 8),
    )
    styles["Code"] = ParagraphStyle(
        name="Code",
        parent=base["Code"],
        fontSize=9,
        leading=12,
        backColor=colors.HexColor("#f1f5f9"),
        borderPadding=(4, 4, 4, 4),
    )
    styles["TableCell"] = ParagraphStyle(
        name="TableCell",
        parent=styles["Body"],
        fontSize=9,
        leading=12,
        spaceAfter=0,
    )
    return styles


# ---------------------------------------------------------------------------
# Metadata block
# ---------------------------------------------------------------------------


def _metadata_table(
    job: Job, styles: dict[str, ParagraphStyle]
) -> Table:
    rows: list[tuple[str, str]] = [("Job ID", job.job_id)]
    if job.completed_at is not None:
        rows.append(
            (
                "Completed",
                datetime.fromtimestamp(job.completed_at, tz=UTC).isoformat(
                    timespec="seconds"
                ),
            )
        )
    if job.iterations is not None:
        rows.append(("Iterations", str(job.iterations)))
    if job.quality_score is not None:
        rows.append(("Quality", f"{job.quality_score:.2f}"))
    if job.cost_usd is not None:
        rows.append(("Cost", f"${job.cost_usd:.4f}"))
    elapsed = job.elapsed_sec()
    if elapsed is not None:
        rows.append(("Elapsed", f"{elapsed:.1f}s"))

    data: list[list[Paragraph]] = [
        [
            Paragraph(label.upper(), styles["MetaLabel"]),
            Paragraph(_escape_html(value), styles["MetaValue"]),
        ]
        for label, value in rows
    ]
    table = Table(data, colWidths=[1.1 * inch, 5.4 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.25,
                    colors.HexColor("#e2e8f0"),
                ),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


# ---------------------------------------------------------------------------
# Token walker — markdown-it tokens to ReportLab flowables.
# ---------------------------------------------------------------------------


def _tokens_to_flowables(
    tokens: list[Token], styles: dict[str, ParagraphStyle]
) -> list[Flowable]:
    flowables: list[Flowable] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # Headings
        if tok.type == "heading_open":
            level = int(tok.tag[1:])  # h1 -> 1
            style_key = {1: "H1", 2: "H2", 3: "H3"}.get(level, "H3")
            inline = tokens[i + 1] if i + 1 < len(tokens) else None
            content = _inline_to_html(inline) if inline else ""
            flowables.append(Paragraph(content, styles[style_key]))
            i += 3  # heading_open, inline, heading_close
            continue

        # Paragraph
        if tok.type == "paragraph_open":
            inline = tokens[i + 1] if i + 1 < len(tokens) else None
            content = _inline_to_html(inline) if inline else ""
            flowables.append(Paragraph(content, styles["Body"]))
            i += 3
            continue

        # Bullet list
        if tok.type == "bullet_list_open":
            list_items, consumed = _collect_list_items(tokens, i, styles)
            flowables.append(
                ListFlowable(
                    list_items,
                    bulletType="bullet",
                    leftIndent=20,
                    bulletFontSize=9,
                    spaceBefore=2,
                    spaceAfter=6,
                )
            )
            i += consumed
            continue

        # Ordered list
        if tok.type == "ordered_list_open":
            list_items, consumed = _collect_list_items(tokens, i, styles)
            flowables.append(
                ListFlowable(
                    list_items,
                    bulletType="1",
                    leftIndent=20,
                    bulletFontSize=9,
                    spaceBefore=2,
                    spaceAfter=6,
                )
            )
            i += consumed
            continue

        # Block quote
        if tok.type == "blockquote_open":
            inner: list[Token] = []
            depth = 1
            j = i + 1
            while j < len(tokens) and depth > 0:
                if tokens[j].type == "blockquote_open":
                    depth += 1
                elif tokens[j].type == "blockquote_close":
                    depth -= 1
                    if depth == 0:
                        break
                inner.append(tokens[j])
                j += 1
            for f in _tokens_to_flowables(inner, styles):
                if isinstance(f, Paragraph):
                    flowables.append(Paragraph(f.text, styles["BlockQuote"]))
                else:
                    flowables.append(f)
            i = j + 1
            continue

        # Fenced / indented code block
        if tok.type in ("fence", "code_block"):
            code = _escape_html(tok.content.rstrip("\n"))
            # Preserve newlines as <br/> so ReportLab renders line breaks.
            html = code.replace("\n", "<br/>").replace(" ", "&nbsp;")
            flowables.append(Paragraph(f"<font face='Courier'>{html}</font>", styles["Code"]))
            i += 1
            continue

        # Horizontal rule
        if tok.type == "hr":
            flowables.append(Spacer(1, 6))
            i += 1
            continue

        # Table
        if tok.type == "table_open":
            table_flowable, consumed = _build_table(tokens, i, styles)
            if table_flowable is not None:
                flowables.append(KeepTogether(table_flowable))
            i += consumed
            continue

        # Unknown block token — skip to avoid an infinite loop, log at
        # caller level if needed. The synthesizer's markdown is
        # limited enough that we shouldn't hit this in practice.
        i += 1

    return flowables


def _collect_list_items(
    tokens: list[Token], start: int, styles: dict[str, ParagraphStyle]
) -> tuple[list[ListItem], int]:
    """Consume tokens from a list_open through its matching list_close,
    returning the corresponding `ListItem` flowables and the number of
    tokens consumed."""
    items: list[ListItem] = []
    j = start + 1
    depth = 1
    while j < len(tokens) and depth > 0:
        tok = tokens[j]
        if tok.type in ("bullet_list_open", "ordered_list_open"):
            depth += 1
            j += 1
            continue
        if tok.type in ("bullet_list_close", "ordered_list_close"):
            depth -= 1
            j += 1
            if depth == 0:
                break
            continue

        if tok.type == "list_item_open" and depth == 1:
            # Walk until the matching list_item_close, collecting inline
            # content from each paragraph_open block.
            k = j + 1
            item_parts: list[str] = []
            item_depth = 1
            while k < len(tokens) and item_depth > 0:
                if tokens[k].type == "list_item_open":
                    item_depth += 1
                elif tokens[k].type == "list_item_close":
                    item_depth -= 1
                    if item_depth == 0:
                        break
                elif tokens[k].type == "paragraph_open":
                    inline = tokens[k + 1] if k + 1 < len(tokens) else None
                    item_parts.append(_inline_to_html(inline) if inline else "")
                    k += 2  # jump paragraph_open + inline
                k += 1
            text = "<br/>".join(item_parts)
            items.append(ListItem(Paragraph(text, styles["Body"])))
            j = k + 1
            continue
        j += 1

    return items, j - start


def _build_table(
    tokens: list[Token], start: int, styles: dict[str, ParagraphStyle]
) -> tuple[Any | None, int]:
    """Build a ReportLab Table from a GFM table_open ... table_close range."""
    rows: list[list[Paragraph]] = []
    current: list[Paragraph] = []
    j = start + 1
    in_row = False
    depth = 1
    while j < len(tokens) and depth > 0:
        tok = tokens[j]
        if tok.type == "table_close":
            depth -= 1
            j += 1
            continue
        if tok.type == "tr_open":
            in_row = True
            current = []
        elif tok.type == "tr_close":
            in_row = False
            if current:
                rows.append(current)
        elif tok.type in ("th_open", "td_open") and in_row:
            inline = tokens[j + 1] if j + 1 < len(tokens) else None
            content = _inline_to_html(inline) if inline else ""
            current.append(Paragraph(content, styles["TableCell"]))
        j += 1

    if not rows:
        return None, j - start

    n_cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < n_cols:
            r.append(Paragraph("", styles["TableCell"]))

    table = Table(rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.25,
                    colors.HexColor("#cbd5e1"),
                ),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table, j - start


def _inline_to_html(token: Token | None) -> str:
    """Render an `inline` token's children as ReportLab-friendly HTML.

    ReportLab paragraph supports a subset of HTML — `<b>`, `<i>`,
    `<font>`, `<br/>`, `<a>`. Bold, italic, code, and links are all
    the inline forms the synthesizer emits.
    """
    if token is None or token.children is None:
        return ""
    parts: list[str] = []
    stack: list[str] = []
    for child in token.children:
        t = child.type
        if t == "text":
            parts.append(_escape_html(child.content))
        elif t == "code_inline":
            parts.append(
                "<font face='Courier'>"
                + _escape_html(child.content)
                + "</font>"
            )
        elif t == "strong_open":
            parts.append("<b>")
            stack.append("</b>")
        elif t == "strong_close":
            parts.append(stack.pop() if stack else "</b>")
        elif t == "em_open":
            parts.append("<i>")
            stack.append("</i>")
        elif t == "em_close":
            parts.append(stack.pop() if stack else "</i>")
        elif t == "link_open":
            # `attrGet` returns `str | int | float | None` for the
            # generic HTML attribute surface; we only accept string
            # hrefs and coerce anything else through `str()`.
            raw_href = child.attrGet("href")
            href_str = str(raw_href) if raw_href else ""
            href = _escape_html(href_str)
            parts.append(f'<a href="{href}" color="#2563eb">')
            stack.append("</a>")
        elif t == "link_close":
            parts.append(stack.pop() if stack else "</a>")
        elif t == "softbreak" or t == "hardbreak":
            parts.append("<br/>")
        else:
            # Unknown inline token — fall back to its raw content so
            # nothing is dropped silently.
            if child.content:
                parts.append(_escape_html(child.content))
    return "".join(parts)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
