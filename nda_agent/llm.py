"""Create the Claude client: the Claude API directly, or Claude in Microsoft Foundry."""

from __future__ import annotations

import os

import anthropic

# Entra ID scope for Claude in Microsoft Foundry.
FOUNDRY_SCOPE = "https://ai.azure.com/.default"


def uses_foundry() -> bool:
    return bool(os.getenv("ANTHROPIC_FOUNDRY_RESOURCE") or os.getenv("ANTHROPIC_FOUNDRY_BASE_URL"))


def make_client() -> anthropic.AsyncAnthropic:
    """Claude API client, or a Foundry client when ANTHROPIC_FOUNDRY_RESOURCE/BASE_URL is set.

    On Foundry, ANTHROPIC_FOUNDRY_API_KEY is used if present; otherwise the app signs in
    with Microsoft Entra ID (managed identity in Azure, or `az login` locally).
    """
    if not uses_foundry():
        return anthropic.AsyncAnthropic()
    if os.getenv("ANTHROPIC_FOUNDRY_API_KEY"):
        return anthropic.AsyncAnthropicFoundry()  # resource/base URL and key read from env
    from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider

    token_provider = get_bearer_token_provider(DefaultAzureCredential(), FOUNDRY_SCOPE)
    return anthropic.AsyncAnthropicFoundry(azure_ad_token_provider=token_provider)
