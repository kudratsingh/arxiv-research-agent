"""The schemas are transcriptions of the prompts, not designs (ADR 0077).

`src/agents/schemas.py` exists to tell the provider what to generate.
It only helps if it asks for what the prompt already asks for: a schema
that has drifted from its prompt makes the model choose between two
instructions, and the one it drops is not predictable.

So the checks here read the agents' `SYSTEM_PROMPT` text and compare it
to the models — in both directions. A field the prompt names and the
schema omits would be dropped from the response; a field the schema
requires and the prompt never mentions is new prompt text arriving
through `output_config.format`, which is the thing ADR 0070 says not to
do while metrics are baselined.
"""

from __future__ import annotations

import json
import re

import anthropic
import pytest
from pydantic import BaseModel

from src.agents.critic import SYSTEM_PROMPT as CRITIC_PROMPT
from src.agents.planner import SYSTEM_PROMPT as PLANNER_PROMPT
from src.agents.schemas import (
    CriticOutput,
    CriticScores,
    PlannerOutput,
    SupervisorOutput,
    VerifierOutput,
)
from src.agents.supervisor import SUPERVISOR_SYSTEM_PROMPT
from src.agents.verifier import VERIFIER_SYSTEM_PROMPT

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _keys_at_indent(prompt: str, spaces: int) -> set[str]:
    """JSON object keys the prompt spells at exactly `spaces` indent.

    The prompts end with a literal JSON template — placeholders and
    `a|b` alternations included, so it does not parse — and the keys of
    that template are the contract. Reading them out of the prompt text
    is what makes this a comparison rather than two hand-kept lists.
    """
    return set(re.findall(rf'^ {{{spaces}}}"(\w+)":', prompt, flags=re.MULTILINE))


#: (schema, prompt, indent) for the four structured agents. The
#: supervisor's prompt is a `.format` template, so its braces are
#: doubled; that does not touch the key lines.
CASES = [
    pytest.param(PlannerOutput, PLANNER_PROMPT, 2, id="planner"),
    pytest.param(CriticOutput, CRITIC_PROMPT, 2, id="critic"),
    pytest.param(SupervisorOutput, SUPERVISOR_SYSTEM_PROMPT, 2, id="supervisor"),
    pytest.param(VerifierOutput, VERIFIER_SYSTEM_PROMPT, 2, id="verifier"),
]


class TestEverySchemaMatchesItsPrompt:
    @pytest.mark.parametrize(("schema", "prompt", "indent"), CASES)
    def test_the_fields_are_exactly_the_keys_the_prompt_asks_for(
        self, schema: type[BaseModel], prompt: str, indent: int
    ) -> None:
        assert set(schema.model_fields) == _keys_at_indent(prompt, indent), (
            f"{schema.__name__} and its prompt disagree about the response "
            "shape. Whichever one moved, the other has to move with it — a "
            "schema that asks for a field the prompt does not describe is "
            "new prompt text (ADR 0070)."
        )

    def test_the_critic_s_nested_scores_match_its_prompt_too(self) -> None:
        """The one nested object, and the one the schema could quietly drop.

        `critic_agent` reads only `average_score`, so nothing in the
        code would notice `scores` disappearing from the schema — but
        the model would stop producing the five dimensions its prompt
        asks it to reason through.
        """
        assert set(CriticScores.model_fields) == _keys_at_indent(CRITIC_PROMPT, 4)

    @pytest.mark.parametrize(
        ("schema", "field", "prompt"),
        [
            pytest.param(
                CriticOutput, "revision_target", CRITIC_PROMPT, id="revision_target"
            ),
            pytest.param(
                VerifierOutput,
                "recommended_action",
                VERIFIER_SYSTEM_PROMPT,
                id="recommended_action",
            ),
        ],
    )
    def test_every_enum_member_is_a_word_the_prompt_uses(
        self, schema: type[BaseModel], field: str, prompt: str
    ) -> None:
        """A member the prompt never offers is a member the model was
        never told about — and, under structured outputs, one it can now
        be forced into."""
        members = anthropic.transform_schema(schema)["properties"][field]["enum"]
        missing = [m for m in members if m and m not in prompt]
        assert not missing, f"{schema.__name__}.{field} offers {missing}, unprompted"


class TestTheSchemaSentToTheModel:
    """What `output_config.format` actually carries."""

    @pytest.mark.parametrize(("schema", "prompt", "indent"), CASES)
    def test_no_class_docstring_reaches_the_wire(
        self, schema: type[BaseModel], prompt: str, indent: int
    ) -> None:
        """Pydantic puts `__doc__` in the schema as `description`.

        This module's docstrings cite ADR numbers and name private
        helpers. Shipping them would add prompt text nobody reviewed as
        prompt text.
        """
        wire = json.dumps(anthropic.transform_schema(schema))
        assert "ADR" not in wire
        assert "_agent" not in wire

    @pytest.mark.parametrize(("schema", "prompt", "indent"), CASES)
    def test_every_field_is_required_and_extras_are_forbidden(
        self, schema: type[BaseModel], prompt: str, indent: int
    ) -> None:
        """No defaults, so a violation raises rather than arriving as a
        plausible-looking value the agent then acts on."""
        transformed = anthropic.transform_schema(schema)
        assert set(transformed["required"]) == set(schema.model_fields)
        assert transformed["additionalProperties"] is False

    def test_the_supervisor_s_action_stays_an_open_string(self) -> None:
        """Its prompt's enum is built per call from `_available_actions()`.

        A static enum here would either offer an action the deployment
        has disabled (`verify` with `ENABLE_VERIFIER=false`) or forbid
        one it has enabled.
        """
        action = anthropic.transform_schema(SupervisorOutput)["properties"][
            "next_action"
        ]
        assert action["type"] == "string"
        assert "enum" not in action
