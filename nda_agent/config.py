"""Settings read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    playbook_path: Path
    provider: str  # "openai" or "anthropic"
    model: str
    effort: str
    redline_author: str
    redline_initials: str
    add_comments: bool
    max_upload_mb: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            playbook_path=Path(os.getenv("PLAYBOOK_PATH", ROOT / "playbooks" / "Unifi - MA NDA Playbook.docx")),
            provider=(provider := _provider()),
            model=os.getenv("NDA_MODEL") or ("gpt-5.2" if provider == "openai" else "claude-opus-5-5"),
            effort=os.getenv("NDA_EFFORT", "high"),
            redline_author=os.getenv("REDLINE_AUTHOR", "Unifi Legal"),
            redline_initials=os.getenv("REDLINE_INITIALS", "UL"),
            add_comments=os.getenv("ADD_COMMENTS", "true").lower() in ("1", "true", "yes"),
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "15")),
        )


def _provider() -> str:
    """NDA_PROVIDER if set; otherwise OpenAI when OpenAI/Azure OpenAI settings are present."""
    explicit = os.getenv("NDA_PROVIDER", "").strip().lower()
    if explicit in ("openai", "anthropic"):
        return explicit
    if explicit:
        raise ValueError(f"NDA_PROVIDER must be 'openai' or 'anthropic', not {explicit!r}")
    if os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "anthropic"
