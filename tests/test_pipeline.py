import asyncio
import io
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import docx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "samples"))
from make_sample_nda import build  # noqa: E402

from nda_agent.config import Settings  # noqa: E402
from nda_agent.pipeline import NDAPipeline  # noqa: E402
from nda_agent.playbook import load_playbook  # noqa: E402
from nda_agent.reviewer import NDAReviewer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

CANNED = {
    "summary": "Seller-friendly NDA.",
    "edits": [
        {"paragraph_id": "p10", "kind": "replace", "target_text": "California", "new_text": "Georgia",
         "playbook_rule": "R41 Choice of Law", "comment": "Governing law to Georgia; fallback NY or DE."},
        {"paragraph_id": "p12", "kind": "replace",
         "target_text": "The parties agree to negotiate in good faith to enter into a definitive agreement "
                        "with respect to the Transaction.",
         "new_text": "", "playbook_rule": "General note", "comment": "No obligation to enter a deal."},
    ],
    "action_items": ["Target name is blank - clear with Jessica."],
}


class FakeStream:
    def __init__(self, calls, **kwargs):
        calls.append(kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=json.dumps(CANNED))],
            usage={},
        )


def fake_client(calls):
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
        stream=lambda **kw: FakeStream(calls, **kw))))


def test_playbook_loads_all_rules():
    text = load_playbook(ROOT / "playbooks" / "Unifi - MA NDA Playbook.docx")
    assert "R1: Entity Names" in text
    assert "Waiver of Consequential Damages" in text
    assert "definitive transaction" in text


def test_pipeline_end_to_end_with_stubbed_model(tmp_path):
    nda = tmp_path / "nda.docx"
    build(nda)
    calls = []
    settings = Settings.from_env()
    reviewer = NDAReviewer(load_playbook(settings.playbook_path), client=fake_client(calls))
    pipeline = NDAPipeline(replace(settings, redline_author="Unifi Legal"), reviewer=reviewer)

    reviewed = asyncio.run(pipeline.run(nda.read_bytes(), turn="second", instructions="Target is Acme"))

    request = calls[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "Waiver of Consequential Damages" in request["system"][0]["text"]
    user = request["messages"][0]["content"]
    assert "Review turn: SECOND" in user and "Target is Acme" in user and "[p10]" in user

    assert len(reviewed.result.applied) == 2 and not reviewed.result.skipped
    out = docx.Document(io.BytesIO(reviewed.docx_bytes))
    assert len(list(out.comments)) == 2
    summary = reviewed.summary_markdown()
    assert "2 tracked edits" in summary and "clear with Jessica" in summary
