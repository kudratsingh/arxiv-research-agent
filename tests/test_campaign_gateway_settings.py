"""Which `Settings` the provider gateway reads during a campaign (W21).

W20's rehearsal reported an asymmetry rather than fixing it: the
admission controller's credential probe was handed the campaign's own
`Settings`, while `src.llm` read the process-global singleton, because
`src.llm` was absent from `execute_campaign`'s `SETTINGS_CONSUMERS` and
`bound_settings` therefore never rebound it. Where one `.env` sits
behind both the difference is invisible; a campaign run under a
`model_copy`ed `Settings` carrying a different key or model is admitted
against one credential and would dial with another.

Two halves, and both are tested here because only the first is visible
in the consumer list:

1. **The name.** `src.llm` is on the list, so `settings` inside the
   gateway is the campaign's object for the length of an episode. That
   is what the *model* rides on: `call_llm` resolves
   `model_name or settings.anthropic_model` per call.
2. **The memo.** The *credential* is read exactly once, at client
   construction, so an episode that inherited `src.llm._client` would
   keep dialling with a client built from somebody else's key however
   the `settings` name is bound. `bound_settings` drops the memo on the
   way in and restores the caller's on the way out.

Its own module rather than a seventh section of
`tests/test_campaign_execution.py`: that module's `full_matrix` fixture
is module-scoped and holds a `MonkeyPatch` context open over
`src.llm._get_client` for the rest of the file, so a test that needs the
real constructor cannot live after it. Nothing here dials or spends.
`anthropic.Anthropic` is replaced by a recorder and `_get_client` by a
fake; the only things measured are which `Settings` the gateway read and
what it put in the request.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

import src.llm as llm_module
from src.campaign.execute import (
    GATEWAY_CLIENT_ATTR,
    GATEWAY_MODULE,
    SETTINGS_CONSUMERS,
    bound_settings,
)
from src.config import Settings
from src.config import settings as shipped_settings

#: A model id the capability table knows and the shipped settings do not
#: name, so "the request named the campaign's model" cannot pass by
#: accident.
CAMPAIGN_MODEL = "claude-opus-4-5"

#: A credential shaped like a real one with no account behind it. Never
#: reaches a transport: every client in this module is a recorder.
CAMPAIGN_KEY = "sk-campaign-scoped-no-account"


def config(**overrides: Any) -> Settings:
    """The shipped settings on a mock, no-cost surface.

    `model_copy` does not validate and `anthropic_api_key` is a
    `SecretStr` (WO-C4) that production code unwraps, so the key is
    wrapped here: a test that passed a bare string would be testing an
    object `Settings` cannot produce.
    """
    base: dict[str, Any] = {
        "use_mock_data": True,
        "enable_tracing": False,
        "enable_metrics": False,
        "enable_checkpointing": False,
    }
    if "anthropic_api_key" in overrides:
        overrides["anthropic_api_key"] = SecretStr(str(overrides["anthropic_api_key"]))
    patched = shipped_settings.model_copy(update={**base, **overrides})
    assert isinstance(patched, Settings)
    return patched


class RecordedClient:
    """What the fake SDK constructor built, and what it was asked to send."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.sent: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(
            with_raw_response=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs: Any) -> Any:
        self.sent.append(kwargs)
        usage = SimpleNamespace(
            input_tokens=1,
            output_tokens=1,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        parsed = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")],
            usage=usage,
            id="msg_w21",
            model=kwargs["model"],
            stop_reason="end_turn",
        )
        return SimpleNamespace(parse=lambda: parsed, retries_taken=0)


def campaign_settings() -> Settings:
    """A campaign whose credential and model are nobody else's."""
    campaign = config(anthropic_api_key=CAMPAIGN_KEY, anthropic_model=CAMPAIGN_MODEL)
    assert (
        campaign.anthropic_api_key.get_secret_value()
        != shipped_settings.anthropic_api_key.get_secret_value()
    )
    assert campaign.anthropic_model != shipped_settings.anthropic_model
    return campaign


@pytest.mark.integration
@pytest.mark.security
class TestTheGatewayReadsTheCampaignsSettings:
    """Both doors read one object, and neither of them is the process's."""

    def test_the_client_is_built_from_the_campaigns_credential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        campaign = campaign_settings()
        built: list[RecordedClient] = []

        def _record(**kwargs: Any) -> RecordedClient:
            client = RecordedClient(**kwargs)
            built.append(client)
            return client

        monkeypatch.setattr(llm_module.anthropic, "Anthropic", _record)
        monkeypatch.setattr(llm_module, "_client", None)

        with bound_settings(campaign):
            assert llm_module.settings is campaign
            llm_module._get_client()

        assert [client.kwargs["api_key"] for client in built] == [CAMPAIGN_KEY]
        assert llm_module.settings is not campaign

    def test_the_request_names_the_campaigns_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The model is read per call, so the binding has to hold then too."""
        campaign = campaign_settings()
        client = RecordedClient(api_key=CAMPAIGN_KEY)
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)
        monkeypatch.setattr(llm_module, "record_llm_call", lambda **_: None)

        with bound_settings(campaign):
            llm_module.call_llm("one bounded question")

        assert [sent["model"] for sent in client.sent] == [CAMPAIGN_MODEL]

    def test_the_memoised_client_does_not_cross_the_boundary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A client built from somebody else's key must not be inherited.

        The half of this fix a consumer-list assertion cannot see: the
        credential is read once, at construction, so rebinding the
        `settings` name alone would leave an episode dialling with
        whatever client the process already had.
        """
        campaign = campaign_settings()
        outer = RecordedClient(api_key="sk-somebody-elses")
        monkeypatch.setattr(llm_module, "_client", outer)
        seen: list[Any] = []

        with bound_settings(campaign):
            seen.append(llm_module._client)

        assert seen == [None]
        assert llm_module._client is outer

    def test_the_memo_is_restored_even_when_the_episode_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One arm's client can no more leak than one arm's settings can."""
        campaign = campaign_settings()
        outer = RecordedClient(api_key="sk-somebody-elses")
        monkeypatch.setattr(llm_module, "_client", outer)

        with (
            pytest.raises(RuntimeError, match="episode blew up"),
            bound_settings(campaign),
        ):
            raise RuntimeError("episode blew up")

        assert llm_module._client is outer
        assert llm_module.settings is not campaign

    def test_the_sentinel_refusal_stays_structural(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A campaign cannot buy its way past the zero-spend sentinel.

        The refusal is a property of the value, not of the object the
        value was read from — so a campaign `Settings` carrying the
        sentinel refuses exactly as the process-global one does, and no
        SDK client is constructed on the way.
        """
        campaign = config(
            anthropic_api_key=llm_module.LOCAL_PREVIEW_DISABLED_API_KEY,
            anthropic_model=CAMPAIGN_MODEL,
        )
        built: list[Any] = []

        def _record(**kwargs: Any) -> Any:
            built.append(kwargs)
            return SimpleNamespace(**kwargs)

        monkeypatch.setattr(llm_module.anthropic, "Anthropic", _record)
        monkeypatch.setattr(llm_module, "_client", None)

        with bound_settings(campaign), pytest.raises(RuntimeError) as refusal:
            llm_module._get_client()

        assert "structurally disables" in str(refusal.value)
        assert built == []

    def test_the_consumer_list_still_names_the_gateway(self) -> None:
        """The pin W20 wrote, inverted and kept where the loop can see it."""
        assert GATEWAY_MODULE in SETTINGS_CONSUMERS
        assert llm_module.__name__ == GATEWAY_MODULE
        assert hasattr(llm_module, GATEWAY_CLIENT_ATTR)
