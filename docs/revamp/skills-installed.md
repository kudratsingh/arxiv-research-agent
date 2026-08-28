# Frontend design skill and tooling audit

Audited: 2026-08-28  
Policy: project-scoped, pinned where possible, minimum necessary installation

## Installed

### Anthropic frontend-design

| Field | Value |
|---|---|
| Source | [`anthropics/skills` at inspected commit](https://github.com/anthropics/skills/tree/3b3fad96af16a10759d930941b4520ba0c40edae/skills/frontend-design) |
| Upstream commit inspected | `3b3fad96af16a10759d930941b4520ba0c40edae` |
| Project location | `.agents/skills/frontend-design/SKILL.md` |
| Registry | `skills-lock.json` |
| Upstream file SHA-256 | `1608ea77fbb6fc30d13a97d12cfa8ebf31358d40f0dd97beed24829d6b3f45dd` |
| Installer record hash | `4eabc66183767153e404b39d1b839b1c37f2d82d86f0a0d7e880a579d8d62336` |
| Scope | Codex project skill; plain Markdown instructions and license only |

Installed with the Skills CLI from the official Anthropic repository. The skill requires a concrete aesthetic thesis, intentional typography/color/composition, and avoidance of generic template patterns. It informed the three directions by requiring:

- one subject-grounded signature element rather than generalized decoration;
- a named token seed and explicit typography roles;
- critique of default dashboard aesthetics before implementation;
- responsive, keyboard, focus, and reduced-motion treatment;
- boldness concentrated in one place so the working surface stays usable.

The installed package contains no executable hooks, network clients, shell scripts, or generated runtime dependency.

## Inspected, not installed as a separate runtime

### Anthropic Claude Code frontend-design plugin

| Field | Value |
|---|---|
| Source | [`anthropics/claude-code/plugins/frontend-design` at inspected commit](https://github.com/anthropics/claude-code/tree/92bb6850f1bb51f4d18b03b23d643642f9d687b6/plugins/frontend-design) |
| Commit inspected | `92bb6850f1bb51f4d18b03b23d643642f9d687b6` |
| Plugin version | `1.1.0` |
| Contents | Manifest, README, `skills/frontend-design/SKILL.md` |

The plugin's embedded `SKILL.md` and the official standalone skill were byte-identical at the inspected commits, including the SHA-256 above. The plugin has no hook or script that would add behavior beyond the guidance. Because this session runs Codex rather than Claude Code, installing the identical project-scoped skill is the active, environment-native equivalent; carrying a second Claude-only manifest would add no capability.

### Anthropic frontend-aesthetics cookbook

| Field | Value |
|---|---|
| Source | [`prompting_for_frontend_aesthetics.ipynb` at inspected commit](https://github.com/anthropics/claude-cookbooks/blob/35f2eec7e44897c537e44441b7dff2f0ecbfb804/coding/prompting_for_frontend_aesthetics.ipynb) |
| Commit inspected | `35f2eec7e44897c537e44441b7dff2f0ecbfb804` |
| Installation | None; research reference only |

Its practical contribution is the design sequence used here: define the visual thesis, build a compact token vocabulary, sketch the composition, name the signature interaction, and explicitly identify the generic patterns to avoid before writing UI code.

## Companion capabilities

| Need from the orchestrator brief | Capability used or selected | Gate 1 result |
|---|---|---|
| Delegated discovery and research | Native Codex collaboration agents | Three bounded specialists covered frontend inventory, backend/domain contracts, and UX/technology research |
| Independent review | A separate collaboration agent | Required after the artifacts are assembled; no author self-approval |
| Current documentation | Official web sources and package registries | Used in preference to secondary summaries; sources recorded in [`01-RESEARCH.md`](01-RESEARCH.md) |
| Browser inspection | Bundled Browser control skill | Skill was inspected, but no browser runtime was connected; `agent.browsers.list()` returned `[]` |
| Browser evidence fallback | Local Chrome + Lighthouse 13.4.1 | Captured screenshots, accessibility audits, and performance artifacts without external product calls |
| App/plugin discovery | Bundled Plugin Management guidance | No additional account connection was necessary for Gate 1 |
| Version-aware documentation MCP | Context7/documentation MCP was not exposed in this session | Fallback: official framework/package documentation and registries, with exact versions and fetched URLs recorded in `01-RESEARCH.md` |
| TDD / brainstorming workflow plugin | Superpowers or an equivalent plugin was not exposed | Fallback: the supplied gated plan/work-order protocol, native planning, existing test suite, and delegated specialists; no executable community workflow hooks installed |
| Code-review plugin | No dedicated code-review plugin was exposed | Fallback: a different native collaboration agent reviews with file/line findings and an approve/reject verdict; review evidence is retained in `REVIEW.md` |

The browser limitation is explicit rather than silently bypassed: Lighthouse supplied the current Chrome evidence, and Phase 4 proposes repository-owned Playwright projects for Chromium, Firefox, WebKit, and mobile.

## Community options evaluated

The search pass explicitly covered [skills.sh](https://skills.sh/), [claude-plugins.dev](https://claude-plugins.dev/), and GitHub “awesome agent skills” list/search results. Registry/list entries were treated as discovery pointers, not provenance; every retained candidate below was checked at its upstream repository. No community skill was installed during discovery.

| Candidate | Why it is credible | Decision |
|---|---|---|
| [Vercel React Best Practices](https://github.com/vercel-labs/agent-skills/tree/main/skills/react-best-practices) | First-party framework ecosystem; performance and React patterns | Reconsider in Phase 3 after architecture; avoid overlapping the official Anthropic design guidance now |
| [Microsoft Playwright CLI](https://github.com/microsoft/playwright-cli) | First-party browser automation from the Playwright project | Prefer repository-owned `@playwright/test` configuration for repeatable CI; CLI skill is optional authoring assistance |
| [Anthropic webapp-testing](https://github.com/anthropics/skills/tree/main/skills/webapp-testing) | Official source, aligned with deterministic browser verification | Candidate for Phase 4 if its then-current instructions complement rather than duplicate the project test harness |
| Community accessibility packs | Could accelerate WCAG checklists | Not installed: broad packs varied in provenance/versioning and cannot replace axe, browser, keyboard, and screen-reader evidence |

## Supply-chain and maintenance rules

1. Install only project-scoped skills from reviewed repositories.
2. Pin source/commit and keep the lockfile in the same pull request.
3. Inspect every instruction file and any referenced scripts before execution.
4. Treat a skill as authoring guidance, never as proof that the UI is accessible or correct.
5. Run application tests and browser evidence independently of the skill that helped create the code.
6. Re-review the upstream diff before upgrading a skill lock.
