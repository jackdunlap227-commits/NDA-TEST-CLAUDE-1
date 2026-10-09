"""OpenAI reviewer (e.g. GPT-5.2), via OpenAI directly or Azure OpenAI in Microsoft Foundry."""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

import openai

from .reviewer import (
    REVIEW_SCHEMA,
    SYSTEM_PROMPT,
    ReviewError,
    ReviewOutput,
    build_user_message,
    parse_review,
)

log = logging.getLogger(__name__)

# Entra ID scope for Azure OpenAI / Foundry. Override with AZURE_OPENAI_SCOPE if your tenant differs.
AZURE_SCOPE = "https://ai.azure.com/.default"


def make_openai_client() -> openai.AsyncOpenAI:
    """OpenAI client, or Azure OpenAI's v1 endpoint when AZURE_OPENAI_ENDPOINT is set.

    On Azure, AZURE_OPENAI_API_KEY is used if present; otherwise the app signs in with
    Microsoft Entra ID (managed identity in Azure, or `az login` locally).
    """
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        return openai.AsyncOpenAI()  # reads OPENAI_API_KEY
    # Accept the bare endpoint or a full "Target URI" copied from the portal; keep scheme + host.
    parts = urlsplit(endpoint if "://" in endpoint else f"https://{endpoint}")
    base_url = f"{parts.scheme}://{parts.netloc}/openai/v1"
    key = os.getenv("AZURE_OPENAI_API_KEY")
    if key:
        return openai.AsyncOpenAI(base_url=base_url + "/", api_key=key)
    from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), os.getenv("AZURE_OPENAI_SCOPE", AZURE_SCOPE)
    )
    return openai.AsyncOpenAI(base_url=base_url + "/", api_key=token_provider)


class OpenAIReviewer:
    def __init__(
        self,
        playbook_text: str,
        model: str = "gpt-5.2",
        effort: str = "high",
        client: openai.AsyncOpenAI | None = None,
    ):
        self.client = client or make_openai_client()
        self.model = model  # on Azure, the deployment name
        self.effort = effort
        # Identical instructions on every request, so OpenAI's automatic prompt caching applies.
        self.instructions = SYSTEM_PROMPT.format(playbook=playbook_text)

    async def review(self, numbered_nda: str, turn: str = "first", instructions: str = "") -> ReviewOutput:
        async with self.client.responses.stream(
            model=self.model,
            instructions=self.instructions,
            input=build_user_message(numbered_nda, turn, instructions),
            reasoning={"effort": self.effort},
            max_output_tokens=64000,
            store=False,
            text={"format": {
                "type": "json_schema",
                "name": "nda_review",
                "schema": REVIEW_SCHEMA,
                "strict": True,
            }},
        ) as stream:
            response = await stream.get_final_response()

        if response.status == "incomplete":
            reason = getattr(response.incomplete_details, "reason", "unknown")
            raise ReviewError(f"The review was cut off ({reason}).")
        for item in response.output:
            for part in getattr(item, "content", None) or []:
                if part.type == "refusal":
                    raise ReviewError(f"The model declined to review this document: {part.refusal}")
        log.info("review usage: %s", response.usage)
        return parse_review(response.output_text)
