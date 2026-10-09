import asyncio

import anthropic
import pytest

from nda_agent.llm import make_client, uses_foundry
from nda_agent.reviewer import NDAReviewer
from test_pipeline import CANNED, fake_client  # noqa: F401  (reuse the stub client)

FOUNDRY_VARS = ("ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_FOUNDRY_BASE_URL", "ANTHROPIC_FOUNDRY_API_KEY")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in FOUNDRY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def test_defaults_to_claude_api():
    assert not uses_foundry()
    client = make_client()
    assert type(client) is anthropic.AsyncAnthropic


def test_foundry_with_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "unifi-ai")
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_API_KEY", "azure-key")
    client = make_client()
    assert isinstance(client, anthropic.AsyncAnthropicFoundry)
    assert str(client.base_url) == "https://unifi-ai.services.ai.azure.com/anthropic/"


def test_foundry_with_entra_id(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "unifi-ai")
    client = make_client()
    assert isinstance(client, anthropic.AsyncAnthropicFoundry)
    # Requests carry an Entra ID bearer token; no API key header is ever attached.
    assert client._azure_ad_token_provider is not None
    assert client.auth_headers == {}


def test_no_server_fallback_on_foundry():
    calls = []
    reviewer = NDAReviewer("playbook", client=fake_client(calls), server_fallback=False)
    asyncio.run(reviewer.review("[p0] text"))
    assert "fallbacks" not in calls[0] and "betas" not in calls[0]
