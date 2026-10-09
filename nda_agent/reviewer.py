"""Ask Claude to review an NDA against the playbook and return structured edits."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import anthropic

from .redline import Edit

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an experienced in-house contracts attorney for Unifi Aviation, LLC ("Unifi"). \
You review non-disclosure agreements that Unifi receives in connection with potential \
acquisitions (buy-side M&A). Unifi is the Receiving Party; the Target Company (often through \
its investment banker or private equity owner) is the Disclosing Party.

Your job is to mark up the NDA exactly as Unifi's legal team would, following the playbook \
below. Your output is turned into Word tracked changes: every deletion appears as a \
strikethrough and every insertion as underlined text, with your comment in the margin.

<playbook>
{playbook}
</playbook>

How to apply the playbook
- Work through the NDA clause by clause and check it against every playbook rule (R1, R2, ...). \
Also apply the note at the end of the playbook (no requirement to enter into a definitive \
transaction).
- Review turn: on the FIRST turn, take the playbook's "Issue" position (Unifi's preferred \
position). On the SECOND turn (the counterparty has already responded to our first markup), \
accept anything the "Standard Fallback" column says is OK to accept on the second turn, and \
only push back where the playbook says to keep pushing (e.g. waiver of consequential damages is \
non-negotiable).
- Where the playbook says to "clear with Jessica" or "clear with the business", still make \
Unifi's preferred edit, and also list it in action_items.
- If a required protection is missing entirely (e.g. a carve-out, a mutual remedies clause, the \
right to retain information under record-retention policies), add it with an \
insert or insert_paragraph_after edit.
- Use the NDA's own defined terms and party names in any new language (e.g. if the NDA says \
"Recipient" and "the Company", write that, not "Receiving Party"). Match the drafting style.
- Leave compliant language alone. Do not make stylistic or grammar edits the playbook does not call for.

How to express edits
- The NDA is given as paragraphs labelled [p0], [p1], ... Each edit applies to exactly one paragraph.
- kind "replace": target_text is the exact, verbatim text to strike (copy it character for \
character from that paragraph) and new_text is what replaces it. Use an empty new_text for a \
pure deletion. Keep edits surgical: strike only the words that must change, not whole \
sentences, so the redline is easy to read. target_text must be long enough to be unique within \
the paragraph (add a few neighbouring words if a short phrase appears more than once).
- kind "insert": new_text is inserted immediately after target_text (verbatim text from the \
paragraph). Include any needed leading space or punctuation in new_text. An empty target_text \
appends to the end of the paragraph.
- kind "insert_paragraph_after": new_text becomes a new paragraph after the given paragraph; \
set target_text to "".
- Never let one edit's target_text overlap another edit's target_text in the same paragraph. \
List edits in document order.
- playbook_rule: the rule ids and topic driving the edit, e.g. "R12 Compelled Disclosure".
- comment: one or two sentences for the margin explaining the change by reference to the \
playbook, and, where useful, the fallback position for the next turn.

Also return
- summary: a short plain-English overview of the NDA and the key changes, for the business team.
- action_items: things a human must do or decide before signing (missing Target name, items to \
clear with Jessica or the business, Unifi entity/affiliate check, anything you were unsure of).
"""

_EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "paragraph_id": {"type": "string", "description": "Paragraph label, e.g. p12"},
        "kind": {"type": "string", "enum": ["replace", "insert", "insert_paragraph_after"]},
        "target_text": {"type": "string"},
        "new_text": {"type": "string"},
        "playbook_rule": {"type": "string"},
        "comment": {"type": "string"},
    },
    "required": ["paragraph_id", "kind", "target_text", "new_text", "playbook_rule", "comment"],
    "additionalProperties": False,
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "edits": {"type": "array", "items": _EDIT_SCHEMA},
        "action_items": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "edits", "action_items"],
    "additionalProperties": False,
}


@dataclass
class ReviewOutput:
    summary: str
    edits: list[Edit]
    action_items: list[str]


class ReviewError(RuntimeError):
    pass


class NDAReviewer:
    def __init__(
        self,
        playbook_text: str,
        model: str = "claude-opus-5-5",
        effort: str = "high",
        client: anthropic.AsyncAnthropic | None = None,
    ):
        self.client = client or anthropic.AsyncAnthropic()
        self.model = model
        self.effort = effort
        # Frozen system prompt so the playbook is served from the prompt cache on every review.
        self.system = [{
            "type": "text",
            "text": SYSTEM_PROMPT.format(playbook=playbook_text),
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }]

    async def review(self, numbered_nda: str, turn: str = "first", instructions: str = "") -> ReviewOutput:
        user = (
            f"Review turn: {turn.upper()}\n"
            + (f"Additional instructions from the reviewer: {instructions}\n" if instructions else "")
            + f"\n<nda>\n{numbered_nda}\n</nda>"
        )
        async with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=64000,
            system=self.system,
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": REVIEW_SCHEMA},
            },
            # Server-side fallback: if a safety classifier declines, retry on the recommended model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            message = await stream.get_final_message()

        if message.stop_reason == "refusal":
            raise ReviewError("The model declined to review this document.")
        if message.stop_reason == "max_tokens":
            raise ReviewError("The review was cut off (document too long for one pass).")
        text = next((b.text for b in message.content if b.type == "text"), None)
        if not text:
            raise ReviewError("The model returned no review.")
        data = json.loads(text)
        log.info("review usage: %s", message.usage)

        edits = [
            Edit(
                paragraph_id=e["paragraph_id"],
                kind=e["kind"],
                target_text=e["target_text"],
                new_text=e["new_text"],
                comment=f'{e["playbook_rule"]}: {e["comment"]}'.strip(": "),
            )
            for e in data["edits"]
        ]
        return ReviewOutput(
            summary=data["summary"],
            edits=edits,
            action_items=data["action_items"],
        )
