# Architecture Decision Records

Every non-trivial design or technical decision in this project gets an
ADR — a short document capturing the context, the decision made, the
alternatives considered, and the consequences. ADRs are written before
or alongside the code that implements them, and are **amended (not
deleted)** when superseded.

## Format

See [`TEMPLATE.md`](TEMPLATE.md). Files are numbered `NNNN-slug.md` and
never renumbered.

## Index

- [0001](0001-use-anthropic-sdk-directly.md) — Use the Anthropic SDK
  directly, not LangChain's wrapper
- [0002](0002-section-aware-chunker.md) — Roll our own section-aware
  chunker over generic markdown splitters

## When to write an ADR

- Choosing between competing libraries or frameworks.
- Choosing between competing algorithmic or architectural approaches.
- Introducing a new external dependency of any weight.
- Establishing a new project-wide convention.
- Reversing a prior ADR (write a new one with `Status: superseded by`).

If you're not sure whether a decision warrants an ADR, err toward
writing one. They're cheap to write and priceless six months later.
