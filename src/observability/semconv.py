"""The OpenTelemetry GenAI conventional names, written down exactly once.

Every `gen_ai.*` string this repository emits is a constant in this
module and nowhere else. That is not tidiness: these names are the
whole reason WO-A07 exists. A dashboard, a vendor cost view or an MCP
instrumentation added later reads *the standard's* names, so a single
character wrong here silently produces telemetry that no off-the-shelf
consumer parses — and a wrong name that is spelled consistently across
five modules looks exactly like a right one.

## What was pinned, and why it is a commit and not a version

The GenAI conventions **left the core `semantic-conventions`
repository** at v1.42.0 and now live in
`open-telemetry/semantic-conventions-genai`. That repository has **no
tags and no releases**, so there is no versioned schema URL to put in
a `Resource` and nothing to pin but a commit. Every definition below
was read out of the model files at:

    open-telemetry/semantic-conventions-genai
    94f432d7126f5884d30a2cdde6f4e89908ebb6fd  (2026-09-03)

    model/gen-ai/registry.yaml   attribute keys and enum members
    model/gen-ai/spans.yaml      span names, kinds, requirement levels
    model/gen-ai/metrics.yaml    metric names, instruments, units

Every one of them carries a `development` stability badge. **These
names are expected to churn**, and this module is where a churn lands:
one file to re-read against a newer commit, one SHA to bump, one place
where "we changed a name" is a reviewable diff rather than a search.
ADR 0066 records the pin and the aliasing policy that protects
dashboards while it moves.

## The name that is wrong in most implementations

`GEN_AI_PROVIDER_NAME` is **`gen_ai.provider.name`**. The older
`gen_ai.system` was renamed and is the single most likely stale string
to appear in code written from memory. It does not appear in this
repository, and `tests/test_genai_conventions.py` fails if it ever
does.

## What is required where (verified, not assumed)

The conventions do **not** require `gen_ai.provider.name` on every
span. `spans.yaml` marks it `required` on `gen_ai.inference.client`
and on the metric attribute group, and does not list it at all on the
four in-process span types this repository emits
(`invoke_agent.internal`, `execute_tool.internal`,
`invoke_workflow.internal`, `plan.internal`). Their required set is
`gen_ai.operation.name`, plus `gen_ai.tool.name` for a tool span. That
resolves a question the summary in `02-STANDARDS.md` §1.2 leaves open:
a local PDF parse has no inference provider, and it does not need one.

## Content capture

None of the opt-in content attributes (`gen_ai.input.messages`,
`gen_ai.output.messages`, `gen_ai.system_instructions`,
`gen_ai.tool.definitions`, …) are defined here, because nothing in
this repository may set them: the telemetry would otherwise carry
paper text, learner text and research queries. The conventions define
exactly one opt-in environment variable,
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`, which
`src.observability.logging.content_capture_enabled` already reads.
`OTEL_SEMCONV_STABILITY_OPT_IN` has **nothing** to do with GenAI
content capture — that claim is a widely-repeated blog error and
appears nowhere in the conventions.
"""

from __future__ import annotations

from typing import Final

#: The commit these names were read from. Quoted in ADR 0066 and
#: asserted by `tests/test_genai_conventions.py` so the pin and the
#: prose cannot drift apart.
SEMCONV_GENAI_REPO: Final = "open-telemetry/semantic-conventions-genai"
SEMCONV_GENAI_COMMIT: Final = "94f432d7126f5884d30a2cdde6f4e89908ebb6fd"

# ---------------------------------------------------------------------------
# Attributes — model/gen-ai/registry.yaml
# ---------------------------------------------------------------------------

#: Required on every GenAI span and metric. Value comes from
#: `OPERATION_*` below.
GEN_AI_OPERATION_NAME: Final = "gen_ai.operation.name"

#: Required on the inference span and on the client metrics. **Not**
#: `gen_ai.system`.
GEN_AI_PROVIDER_NAME: Final = "gen_ai.provider.name"

GEN_AI_REQUEST_MODEL: Final = "gen_ai.request.model"
GEN_AI_REQUEST_MAX_TOKENS: Final = "gen_ai.request.max_tokens"
GEN_AI_REQUEST_TEMPERATURE: Final = "gen_ai.request.temperature"

GEN_AI_RESPONSE_ID: Final = "gen_ai.response.id"
GEN_AI_RESPONSE_MODEL: Final = "gen_ai.response.model"
GEN_AI_RESPONSE_FINISH_REASONS: Final = "gen_ai.response.finish_reasons"

GEN_AI_USAGE_INPUT_TOKENS: Final = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS: Final = "gen_ai.usage.output_tokens"
#: Anthropic's two prompt-cache buckets (ADR 0022) map onto conventional
#: names rather than needing private ones.
GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS: Final = "gen_ai.usage.cache_read.input_tokens"
GEN_AI_USAGE_CACHE_WRITE_INPUT_TOKENS: Final = "gen_ai.usage.cache_write.input_tokens"

GEN_AI_AGENT_NAME: Final = "gen_ai.agent.name"
GEN_AI_TOOL_NAME: Final = "gen_ai.tool.name"
GEN_AI_TOOL_TYPE: Final = "gen_ai.tool.type"
GEN_AI_WORKFLOW_NAME: Final = "gen_ai.workflow.name"
#: The job's `conversation_id` (ADR 0032) is exactly this attribute.
GEN_AI_CONVERSATION_ID: Final = "gen_ai.conversation.id"

#: Required on `gen_ai.client.token.usage`; `input` or `output`.
GEN_AI_TOKEN_TYPE: Final = "gen_ai.token.type"
TOKEN_TYPE_INPUT: Final = "input"
TOKEN_TYPE_OUTPUT: Final = "output"

#: Stable core-semconv attribute (not GenAI), used on every span and
#: duration histogram that can fail. The convention is the exception
#: class name or a domain-specific code — never a message.
ERROR_TYPE: Final = "error.type"

#: Stable core-semconv attributes for the peer the client talked to.
SERVER_ADDRESS: Final = "server.address"

# ---------------------------------------------------------------------------
# `gen_ai.operation.name` enum members this repository uses
# ---------------------------------------------------------------------------

OPERATION_CHAT: Final = "chat"
OPERATION_INVOKE_AGENT: Final = "invoke_agent"
OPERATION_INVOKE_WORKFLOW: Final = "invoke_workflow"
OPERATION_EXECUTE_TOOL: Final = "execute_tool"
OPERATION_PLAN: Final = "plan"

#: The full enum, for a test that proves the five above are members of
#: it rather than plausible-looking inventions.
OPERATION_NAMES: Final[frozenset[str]] = frozenset(
    {
        OPERATION_CHAT,
        "generate_content",
        "text_completion",
        "embeddings",
        "retrieval",
        OPERATION_EXECUTE_TOOL,
        "create_agent",
        OPERATION_INVOKE_AGENT,
        OPERATION_INVOKE_WORKFLOW,
        OPERATION_PLAN,
        "fetch_response",
    }
)

# ---------------------------------------------------------------------------
# `gen_ai.provider.name` enum member
# ---------------------------------------------------------------------------

#: The only provider this repository calls. A member of the registry's
#: enum, not a free string — `aws.bedrock` or `azure.ai.openai` would
#: be the value if the client changed, which is why it is a constant.
PROVIDER_ANTHROPIC: Final = "anthropic"

# ---------------------------------------------------------------------------
# `gen_ai.tool.type` values
# ---------------------------------------------------------------------------

#: A tool the agent runs that calls an external API on the agent's
#: side — arXiv, Semantic Scholar, a PDF fetch.
TOOL_TYPE_EXTENSION: Final = "extension"
#: A tool that queries data for a retrieval task — the embedding
#: ranker over candidate papers.
TOOL_TYPE_DATASTORE: Final = "datastore"

# ---------------------------------------------------------------------------
# Metrics — model/gen-ai/metrics.yaml. All histograms.
# ---------------------------------------------------------------------------

METRIC_CLIENT_TOKEN_USAGE: Final = "gen_ai.client.token.usage"
UNIT_TOKEN: Final = "{token}"

METRIC_CLIENT_OPERATION_DURATION: Final = "gen_ai.client.operation.duration"

METRIC_INVOKE_AGENT_DURATION: Final = "gen_ai.invoke_agent.duration"
#: The two per-invocation process counters the conventions already
#: name for an agent system: how many model calls and how many tool
#: calls one agent invocation made.
METRIC_INVOKE_AGENT_INFERENCE_CALLS: Final = "gen_ai.invoke_agent.inference_calls"
UNIT_INFERENCE_CALL: Final = "{inference_call}"
METRIC_INVOKE_AGENT_TOOL_CALLS: Final = "gen_ai.invoke_agent.tool_calls"
UNIT_TOOL_CALL: Final = "{tool_call}"

METRIC_EXECUTE_TOOL_DURATION: Final = "gen_ai.execute_tool.duration"
METRIC_INVOKE_WORKFLOW_DURATION: Final = "gen_ai.invoke_workflow.duration"

#: Seconds. The conventions are explicit that GenAI durations are in
#: seconds, not milliseconds.
UNIT_SECOND: Final = "s"

# ---------------------------------------------------------------------------
# This repository's own identities
# ---------------------------------------------------------------------------

#: `gen_ai.workflow.name` values. One per compiled graph (ADR 0057),
#: which is also the `job.kind` axis job SLOs are cut along — so the
#: workflow name and the job kind are deliberately the same two
#: strings rather than two vocabularies for one distinction.
WORKFLOW_RESEARCH: Final = "research"
WORKFLOW_SESSION: Final = "session"

#: `gen_ai.tool.name` values. Bounded by construction: a tool span is
#: opened with one of these constants, never with a caller-supplied
#: string, which is what keeps the tool metrics' cardinality finite.
TOOL_ARXIV_SEARCH: Final = "arxiv_search"
TOOL_SEMANTIC_SCHOLAR_SEARCH: Final = "semantic_scholar_search"
TOOL_SEMANTIC_SCHOLAR_REFERENCES: Final = "semantic_scholar_references"
TOOL_PDF_PARSE: Final = "pdf_parse"
TOOL_EMBEDDING_RANK: Final = "embedding_rank"

TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        TOOL_ARXIV_SEARCH,
        TOOL_SEMANTIC_SCHOLAR_SEARCH,
        TOOL_SEMANTIC_SCHOLAR_REFERENCES,
        TOOL_PDF_PARSE,
        TOOL_EMBEDDING_RANK,
    }
)

#: The graph node whose invocation is a `plan` span rather than a
#: generic `invoke_agent` one. The conventions say `plan` SHOULD only
#: be reported when the instrumentation can *reliably* tell planning
#: from generic reasoning; here it can, because planning is a named
#: node of the graph rather than an inferred phase.
PLANNER_AGENT_NAME: Final = "planner"


def operation_for_agent(agent_name: str) -> str:
    """Return the conventional operation name for one graph node.

    The planner decomposes the task before anything executes it, which
    is precisely what `plan` is defined to mean; every other node is a
    plain `invoke_agent`.

    Args:
        agent_name: The graph node's name.

    Returns:
        `plan` for the planner, `invoke_agent` for everything else.
    """
    if agent_name == PLANNER_AGENT_NAME:
        return OPERATION_PLAN
    return OPERATION_INVOKE_AGENT


def span_name(operation: str, target: str | None) -> str:
    """Build a conventional span name: `{operation} {target}`.

    The conventions specify `{gen_ai.operation.name} {identity}` for
    every span type here — `chat {model}`, `invoke_agent {agent}`,
    `execute_tool {tool}`, `invoke_workflow {workflow}`, `plan {agent}`
    — and say to fall back to the bare operation when the identity is
    not readily available.

    Args:
        operation: A member of `OPERATION_NAMES`.
        target: The model / agent / tool / workflow identity, or None.

    Returns:
        The span name.
    """
    return f"{operation} {target}" if target else operation
