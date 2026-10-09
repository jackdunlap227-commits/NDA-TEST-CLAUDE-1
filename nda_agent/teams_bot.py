"""Microsoft Teams front end for the NDA agent (Microsoft 365 Agents SDK).

Flow in a 1:1 chat with the bot:
  1. The user attaches an NDA (.docx) and optionally types notes, e.g. "second turn".
  2. The bot acknowledges right away, then reviews in the background (Teams times
     out requests after ~15 seconds; a review takes a minute or two).
  3. The bot posts the summary and a file-consent card; when the user clicks
     Allow, the redlined .docx is uploaded into the chat (the user's OneDrive).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass

import aiohttp
from microsoft_agents.activity import (
    Activity,
    ActivityTypes,
    Attachment,
    InvokeResponse,
)
from microsoft_agents.hosting.core import AgentApplication, TurnContext, TurnState

from .pipeline import NDAPipeline

log = logging.getLogger(__name__)

TEAMS_FILE_DOWNLOAD = "application/vnd.microsoft.teams.file.download.info"
FILE_CONSENT_CARD = "application/vnd.microsoft.teams.card.file.consent"
FILE_INFO_CARD = "application/vnd.microsoft.teams.card.file.info"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

WELCOME = (
    "Hi! I review M&A (buy-side) NDAs against the Unifi playbook.\n\n"
    "**Attach the NDA as a Word (.docx) file** and send it. I'll return a redlined copy with "
    "tracked changes (strikethroughs and insertions) and margin comments citing the playbook.\n\n"
    "Optional notes in the same message:\n"
    "- `second turn` - the counterparty has responded to our first markup; apply the "
    "playbook's second-turn fallbacks\n"
    "- anything else (e.g. *Target is Acme Corp; receiving entity is Unifi Aviation, LLC*) is "
    "passed to the reviewer as instructions"
)

_SECOND_TURN = re.compile(r"\b(second|2nd)\s+(turn|pass|round)\b", re.I)


@dataclass
class _PendingFile:
    name: str
    data: bytes
    created: float


class PendingFiles:
    """Redlines waiting for the user to accept the upload card.

    In-memory, so it assumes a single app instance; swap for Blob storage if you scale out.
    """

    TTL_SECONDS = 24 * 3600

    def __init__(self):
        self._files: dict[str, _PendingFile] = {}

    def put(self, name: str, data: bytes) -> str:
        self._expire()
        key = uuid.uuid4().hex
        self._files[key] = _PendingFile(name, data, time.time())
        return key

    def pop(self, key: str) -> _PendingFile | None:
        return self._files.pop(key, None)

    def restore(self, key: str, pending_file: _PendingFile) -> None:
        self._files[key] = pending_file

    def _expire(self):
        cutoff = time.time() - self.TTL_SECONDS
        for key in [k for k, f in self._files.items() if f.created < cutoff]:
            del self._files[key]


def register_handlers(app: AgentApplication[TurnState], pipeline: NDAPipeline, max_upload_mb: int) -> None:
    pending = PendingFiles()
    background: set[asyncio.Task] = set()

    @app.conversation_update("membersAdded")
    async def on_members_added(context: TurnContext, _state: TurnState):
        for member in context.activity.members_added or []:
            if member.id != context.activity.recipient.id:
                await context.send_activity(WELCOME)

    @app.activity(ActivityTypes.message)
    async def on_message(context: TurnContext, _state: TurnState):
        files = [a for a in (context.activity.attachments or []) if a.content_type == TEAMS_FILE_DOWNLOAD]
        if not files:
            await context.send_activity(WELCOME)
            return
        attachment = files[0]
        name = attachment.name or "NDA.docx"
        content = attachment.content or {}
        file_type = (content.get("fileType") or name.rsplit(".", 1)[-1]).lower()
        if file_type != "docx":
            await context.send_activity(
                f"I can only redline Word documents (.docx); **{name}** is a .{file_type} file. "
                "If you only have a PDF, open it in Word, save as .docx, and send it again."
            )
            return

        text = (context.activity.text or "").strip()
        turn = "second" if _SECOND_TURN.search(text) else "first"
        instructions = _SECOND_TURN.sub("", text).strip(" ,.;-")

        try:
            data = await _download(content["downloadUrl"], max_upload_mb)
        except Exception as exc:  # noqa: BLE001 - report any download failure to the user
            log.exception("download failed")
            await context.send_activity(f"I couldn't download **{name}**: {exc}")
            return

        await context.send_activity(
            f"Reviewing **{name}** against the playbook ({turn} turn). "
            "This usually takes 1-3 minutes; I'll post the redline here when it's ready."
        )

        async def review_and_reply(proactive: TurnContext):
            try:
                reviewed = await pipeline.run(data, turn=turn, instructions=instructions)
            except Exception as exc:  # noqa: BLE001
                log.exception("review failed")
                await proactive.send_activity(f"Sorry, the review of **{name}** failed: {exc}")
                return
            out_name = f"{name.rsplit('.', 1)[0]} - Unifi redline.docx"
            key = pending.put(out_name, reviewed.docx_bytes)
            await proactive.send_activity(reviewed.summary_markdown())
            await proactive.send_activity(Activity(
                type=ActivityTypes.message,
                attachments=[Attachment(
                    content_type=FILE_CONSENT_CARD,
                    name=out_name,
                    content={
                        "description": "Redlined NDA with tracked changes and playbook comments",
                        "sizeInBytes": len(reviewed.docx_bytes),
                        "acceptContext": {"fileKey": key},
                        "declineContext": {"fileKey": key},
                    },
                )],
            ))

        # Continue outside this HTTP request so Teams doesn't time it out.
        adapter, identity, activity = context.adapter, context.identity, context.activity

        async def run_in_background():
            try:
                await adapter.continue_conversation_with_claims(identity, activity, review_and_reply)
            except Exception:  # noqa: BLE001
                log.exception("background review crashed")

        task = asyncio.create_task(run_in_background())
        background.add(task)
        task.add_done_callback(background.discard)

    def _is_file_consent(context: TurnContext) -> bool:
        return context.activity.type == ActivityTypes.invoke and context.activity.name == "fileConsent/invoke"

    async def on_file_consent(context: TurnContext, _state: TurnState):
        value = context.activity.value or {}
        key = (value.get("context") or {}).get("fileKey", "")
        stored = pending.pop(key)
        if value.get("action") == "accept" and stored is not None:
            info = value.get("uploadInfo") or {}
            try:
                await _upload(info["uploadUrl"], stored.data)
                await context.send_activity(Activity(
                    type=ActivityTypes.message,
                    attachments=[Attachment(
                        content_type=FILE_INFO_CARD,
                        name=info.get("name", stored.name),
                        content_url=info["contentUrl"],
                        content={"uniqueId": info.get("uniqueId"), "fileType": info.get("fileType", "docx")},
                    )],
                ))
            except Exception as exc:  # noqa: BLE001
                log.exception("upload failed")
                pending.restore(key, stored)  # let the user retry
                await context.send_activity(f"Uploading the redline failed: {exc}")
        elif value.get("action") == "accept":
            await context.send_activity("That redline has expired; please send the NDA again.")
        else:
            await context.send_activity("OK, I won't upload the redline.")
        await context.send_activity(Activity(type=ActivityTypes.invoke_response, value=InvokeResponse(status=200)))

    app.add_route(_is_file_consent, on_file_consent, is_invoke=True)

    @app.error
    async def on_error(context: TurnContext, error: Exception):
        log.exception("unhandled error", exc_info=error)
        await context.send_activity("Sorry, something went wrong. Please try again.")


async def _download(url: str, max_mb: int) -> bytes:
    limit = max_mb * 1024 * 1024
    async with aiohttp.ClientSession() as session, session.get(url) as resp:
        resp.raise_for_status()
        data = await resp.content.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"file is larger than {max_mb} MB")
    return data


async def _upload(upload_url: str, data: bytes) -> None:
    headers = {
        "Content-Length": str(len(data)),
        "Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}",
        "Content-Type": DOCX_MIME,
    }
    async with aiohttp.ClientSession() as session, session.put(upload_url, data=data, headers=headers) as resp:
        resp.raise_for_status()
