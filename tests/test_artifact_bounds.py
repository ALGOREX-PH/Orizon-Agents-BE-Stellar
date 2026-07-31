"""Generated artifact content is bounded.

The whole HTML is re-sent to the critic and then retained in `state.tasks` for
200 tasks on a 512 MB box, so an unbounded `content` field is a cost, latency
and memory problem. The bound has to degrade the artifact, never fail the run:
the user has already paid for the steps that produced it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.registry import WORKERS
from app.agents.workers.code_gen import (
    MAX_ARTIFACT_CHARS,
    CodeArtifact,
    clamp_artifact_content,
    coerce_artifact,
)

ARTIFACTS = sorted((Path(__file__).resolve().parent.parent / "app" / "demo_kits" / "artifacts").glob("*.html"))

OVERSIZED = "<!doctype html>\n<html>\n<head></head>\n<body>\n<script>\n" + ("const pad = 1;\n" * 60_000)


def _artifact_payload(content: str) -> dict[str, Any]:
    return {
        "title": "t",
        "summary": "s",
        "files": [{"path": "index.html", "language": "html", "content": content}],
        "entry": "index.html",
        "preview_html": content,
    }


def test_oversized_content_is_clamped_instead_of_rejected():
    assert len(OVERSIZED) > MAX_ARTIFACT_CHARS * 3
    art = CodeArtifact.model_validate(_artifact_payload(OVERSIZED))
    assert len(art.files[0].content) <= MAX_ARTIFACT_CHARS + 256
    assert len(art.preview_html) <= MAX_ARTIFACT_CHARS + 256


def test_clamped_html_is_closed_off_so_it_still_parses():
    clamped = clamp_artifact_content(OVERSIZED)
    assert "artifact truncated at" in clamped
    assert clamped.rstrip().endswith("</html>")
    # The cut never leaves a dangling <script>.
    assert clamped.lower().rfind("</script") > clamped.lower().rfind("<script")


def test_content_at_or_under_the_bound_is_untouched():
    small = "<html><body><script>const x = 1;</script></body></html>"
    assert clamp_artifact_content(small) == small
    assert clamp_artifact_content("a" * MAX_ARTIFACT_CHARS) == "a" * MAX_ARTIFACT_CHARS


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_shipped_demo_artifacts_fit_well_inside_the_bound(path):
    """The ceiling must never be tight enough to clip real artifacts."""
    raw = path.read_text(encoding="utf-8")
    assert len(raw) < MAX_ARTIFACT_CHARS
    assert clamp_artifact_content(raw) == raw


def test_coerce_artifact_survives_an_oversized_json_response():
    payload = json.dumps(_artifact_payload(OVERSIZED))
    art = coerce_artifact(payload)  # must not raise
    assert len(art.preview_html) <= MAX_ARTIFACT_CHARS + 256


def test_code_gen_run_handles_an_oversized_generation(monkeypatch):
    """End to end through the worker: a runaway model response degrades to a
    clamped artifact rather than an unhandled exception mid-workflow."""
    worker = WORKERS["agt_11c0"]

    async def fake_arun(prompt: str, *a: Any, **kw: Any) -> Any:
        return SimpleNamespace(content=json.dumps(_artifact_payload(OVERSIZED)))

    monkeypatch.setattr(worker._agent, "arun", fake_arun)
    out = asyncio.run(worker.run("build a huge dashboard", "implement it"))

    assert out["artifact"]["preview_html"]
    # The clamp lands under the ceiling; the CSP meta is injected afterwards,
    # so allow for that small fixed addition.
    assert out["counts"]["bytes"] <= MAX_ARTIFACT_CHARS + 1024
    assert "artifact truncated at" in out["artifact"]["preview_html"]
    assert "Content-Security-Policy" in out["artifact"]["preview_html"]
