"""Review an NDA from the command line (handy for testing without Teams).

    python -m nda_agent.cli path/to/nda.docx [-o redlined.docx] [--turn second] [--note "..."]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from .config import Settings
from .pipeline import NDAPipeline


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Redline an NDA against the playbook.")
    parser.add_argument("nda", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--turn", choices=["first", "second"], default="first")
    parser.add_argument("--note", default="", help="Extra instructions for the reviewer")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    pipeline = NDAPipeline(Settings.from_env())
    reviewed = asyncio.run(pipeline.run(args.nda.read_bytes(), turn=args.turn, instructions=args.note))
    out = args.output or args.nda.with_name(f"{args.nda.stem} - Unifi redline.docx")
    out.write_bytes(reviewed.docx_bytes)
    print(reviewed.summary_markdown())
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
