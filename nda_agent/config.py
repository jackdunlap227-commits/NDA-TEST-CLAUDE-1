"""Settings read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    playbook_path: Path
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
            model=os.getenv("NDA_MODEL", "claude-opus-5-5"),
            effort=os.getenv("NDA_EFFORT", "high"),
            redline_author=os.getenv("REDLINE_AUTHOR", "Unifi Legal"),
            redline_initials=os.getenv("REDLINE_INITIALS", "UL"),
            add_comments=os.getenv("ADD_COMMENTS", "true").lower() in ("1", "true", "yes"),
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "15")),
        )
