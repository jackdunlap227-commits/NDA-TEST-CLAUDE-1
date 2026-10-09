import asyncio
import json
from types import SimpleNamespace

import openai
import pytest

from nda_agent.config import Settings
from nda_agent.openai_reviewer import OpenAIReviewer, make_openai_client
from nda_agent.pipeline import NDAPipeline
from nda_agent.reviewer import ReviewError
from test_pipeline import CANNED

ENV_VARS = ("NDA_PROVIDER", "NDA_MODEL", "OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY",
            "ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_FOUNDRY_API_KEY")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def fake_openai(calls, response):
    class Stream:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_final_response(self):
            return response

    return SimpleNamespace(responses=SimpleNamespace(stream=lambda **kw: Stream(**kw)))


def ok_response(payload=CANNED):
    text = json.dumps(payload)
    message = SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text=text)])
    return SimpleNamespace(status="completed", incomplete_details=None, output=[message],
                           output_text=text, usage={})


def test_openai_request_shape_and_parsing():
    calls = []
    reviewer = OpenAIReviewer("PLAYBOOK TEXT", client=fake_openai(calls, ok_response()))
    review = asyncio.run(reviewer.review("[p0] hello", turn="second", instructions="Target is Acme"))
    req = calls[0]
    assert req["model"] == "gpt-5.2"
    assert req["reasoning"] == {"effort": "high"}
    assert req["text"]["format"]["type"] == "json_schema" and req["text"]["format"]["strict"] is True
    assert "PLAYBOOK TEXT" in req["instructions"]
    assert "Review turn: SECOND" in req["input"] and "Target is Acme" in req["input"]
    assert len(review.edits) == 2 and review.action_items


def test_openai_refusal_and_cutoff_raise():
    refusal = SimpleNamespace(status="completed", incomplete_details=None, output_text="", usage={},
                              output=[SimpleNamespace(content=[SimpleNamespace(type="refusal", refusal="no")])])
    with pytest.raises(ReviewError, match="declined"):
        asyncio.run(OpenAIReviewer("p", client=fake_openai([], refusal)).review("[p0] x"))
    cut = SimpleNamespace(status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                          output=[], output_text="", usage={})
    with pytest.raises(ReviewError, match="cut off"):
        asyncio.run(OpenAIReviewer("p", client=fake_openai([], cut)).review("[p0] x"))


def test_provider_selection(monkeypatch):
    assert Settings.from_env().provider == "anthropic"
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://unifi-ai.openai.azure.com")
    settings = Settings.from_env()
    assert settings.provider == "openai" and settings.model == "gpt-5.2"
    assert isinstance(NDAPipeline(settings).reviewer, OpenAIReviewer)
    monkeypatch.setenv("NDA_PROVIDER", "anthropic")
    assert Settings.from_env().model == "claude-opus-5-5"


def test_azure_client_with_key_and_with_entra(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://unifi-ai.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    client = make_openai_client()
    assert str(client.base_url) == "https://unifi-ai.openai.azure.com/openai/v1/"
    assert client.api_key == "azure-key"
    monkeypatch.delenv("AZURE_OPENAI_API_KEY")
    client = make_openai_client()
    assert isinstance(client, openai.AsyncOpenAI)
    assert callable(client._api_key_provider)  # Entra ID token provider, no key


def test_endpoint_accepts_target_uri(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT",
                       "https://unifi-ai.openai.azure.com/openai/responses?api-version=2025-04-01-preview")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    assert str(make_openai_client().base_url) == "https://unifi-ai.openai.azure.com/openai/v1/"
