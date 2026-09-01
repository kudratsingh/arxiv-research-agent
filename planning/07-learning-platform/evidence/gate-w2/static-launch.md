# WO-W16 static publication and launch record

Status: **PREPARED, NOT PUBLISHED OR SENT**

Prepared: 2026-09-01  
W-OD-3 licensing approval: _pending_  
W-OD-4 host and waitlist mechanism: _pending_  
Published URL: _pending_  
Launch date: _pending_

## Build

Local review preview (noindex, no signup collection):

```bash
.venv/bin/python -m src.content.static_publication \
  --preview \
  --output /tmp/reading-first-papers-preview
```

Production build, only after W-OD-2/3/4 and owner review have moved the
manifest to `published`:

```bash
.venv/bin/python -m src.content.static_publication \
  --waitlist-url '<owner-selected https form or mailto>' \
  --output /tmp/reading-first-papers-public
```

The production command refuses today's proposed manifest. The emitted artifact
is standalone HTML/CSS: no product API, credentials, analytics, tracking script,
or bundled application runtime.

## Draft launch posts — owner sends once

These drafts are deliberately unsent and contain a URL placeholder. The owner
chooses the channel accounts, timing, and final wording.

### Hacker News

**Title:** Show HN: A guided path through the papers that built modern language models

I kept watching people open the Transformer paper as if it appeared from
nowhere. I made a reading sequence that starts with word vectors and seq2seq,
then follows each architectural problem to attention, Transformers, scaling,
and preference training. Every entry says why it comes next, what vocabulary
you need, and what later work corrected. Source pages are linked; no PDFs are
re-hosted. The longer-term project is an evidence-grounded reading mentor.

Path: `<PUBLISHED_URL>`  
Build: <https://github.com/kudratsingh/arxiv-research-agent>

### r/MachineLearning

**[P] Reading your first papers — an ordered, link-out path from word2vec to RLHF**

This is a small experiment in treating a reading list as an argument rather
than a bibliography. The sequence names the problem each paper inherits, the
sections worth reading closely, prerequisite vocabulary, and what has since
superseded the claim. The page is static and has no analytics; the waitlist is
only for people interested in piloting the guided-reading mentor.

`<PUBLISHED_URL>`

### X

The Transformer paper is easier when it is the fifth answer, not the first
wall. I built an ordered path from word2vec → seq2seq → attention →
Transformers → scaling → preference training, with honest “what superseded
this” notes. `<PUBLISHED_URL>`

## Outcome — fill regardless of result

| Measure | Value | Source |
|---|---:|---|
| Unique visits in the observation window | _pending_ | Host server logs, if available |
| Waitlist signups | _pending_ | Owner-selected external form or mailto count |
| Launch posts actually sent | _pending_ | Permalinks above |

No client analytics are added to obtain these numbers. A null result is a
finding about distribution, not permission to invent a better-looking metric.
