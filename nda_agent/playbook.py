"""Load the negotiation playbook (.docx or .md/.txt) into plain text for the prompt."""

from __future__ import annotations

from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


def load_playbook(path: str | Path) -> str:
    path = Path(path)
    if path.suffix.lower() == ".docx":
        return _docx_to_text(path)
    return path.read_text(encoding="utf-8")


def _docx_to_text(path: Path) -> str:
    document = docx.Document(str(path))
    lines: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = Paragraph(child, document).text.strip()
            if text:
                lines.append(text)
        elif child.tag == qn("w:tbl"):
            lines.extend(_table_to_text(Table(child, document)))
    return "\n".join(lines)


def _table_to_text(table: Table) -> list[str]:
    """Render each row as a numbered rule: ``Topic | Issue | Fallback``."""
    rows = []
    for row in table.rows:
        cells, seen = [], set()
        for cell in row.cells:
            if id(cell._tc) in seen:  # merged cells repeat
                continue
            seen.add(id(cell._tc))
            cells.append(" ".join(cell.text.split("\n")).strip())
        rows.append(cells)
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    out = ["", "| " + " | ".join(header) + " |"]
    for i, cells in enumerate(body, start=1):
        if len(cells) < len(header):
            cells = cells + ["(see note)"] * (len(header) - len(cells))
        out.append(f"| R{i}: " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    out.append("")
    return out
