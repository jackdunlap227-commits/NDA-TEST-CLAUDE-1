"""End-to-end: original NDA bytes in, redlined NDA bytes + review summary out."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import Settings
from .llm import make_client, uses_foundry
from .playbook import load_playbook
from .redline import ApplyResult, RedlineDocument
from .openai_reviewer import OpenAIReviewer
from .reviewer import NDAReviewer, ReviewOutput

log = logging.getLogger(__name__)


@dataclass
class ReviewedNDA:
    docx_bytes: bytes
    review: ReviewOutput
    result: ApplyResult

    def summary_markdown(self) -> str:
        lines = ["**Summary**", self.review.summary, ""]
        lines.append(f"**Changes made:** {len(self.result.applied)} tracked edits")
        if self.result.skipped:
            lines.append(
                f"**Needs manual edit:** {len(self.result.skipped)} suggestion(s) could not be placed "
                "automatically; they are left as comments in the document:"
            )
            lines += [f"- {e.comment or e.new_text} ({why})" for e, why in self.result.skipped]
        if self.review.action_items:
            lines += ["", "**Action items before signing**"]
            lines += [f"- {item}" for item in self.review.action_items]
        return "\n".join(lines)


class NDAPipeline:
    def __init__(self, settings: Settings, reviewer: NDAReviewer | OpenAIReviewer | None = None):
        self.settings = settings
        self.reviewer = reviewer or self._make_reviewer(settings)

    @staticmethod
    def _make_reviewer(settings: Settings) -> NDAReviewer | OpenAIReviewer:
        playbook = load_playbook(settings.playbook_path)
        if settings.provider == "openai":
            return OpenAIReviewer(playbook, model=settings.model, effort=settings.effort)
        return NDAReviewer(
            playbook,
            model=settings.model,
            effort=settings.effort,
            client=make_client(),
            server_fallback=not uses_foundry(),
        )

    async def run(self, docx_bytes: bytes, turn: str = "first", instructions: str = "") -> ReviewedNDA:
        doc = RedlineDocument(docx_bytes, author=self.settings.redline_author,
                              initials=self.settings.redline_initials)
        numbered = doc.numbered_text()
        if not numbered.strip():
            raise ValueError("The document has no readable text (is it a scanned image?).")
        review = await self.reviewer.review(numbered, turn=turn, instructions=instructions)
        result = doc.apply(review.edits, add_comments=self.settings.add_comments)
        log.info("applied %d edits, skipped %d", len(result.applied), len(result.skipped))
        return ReviewedNDA(doc.save(), review, result)
