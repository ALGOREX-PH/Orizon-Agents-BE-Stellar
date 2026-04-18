from __future__ import annotations

from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from ...config import settings
from .base import Worker


class ArtifactFile(BaseModel):
    path: str
    language: str  # "html" | "css" | "js" | "tsx" | "python"
    content: str


class CodeArtifact(BaseModel):
    title: str = Field(..., max_length=80)
    summary: str = Field(..., max_length=280)
    files: list[ArtifactFile] = Field(..., min_length=1, max_length=5)
    entry: str = Field(..., description="Path of the main file, matches one of files[].path")
    preview_html: str = Field(
        ..., description="Self-contained HTML document for the sandboxed preview iframe"
    )


INSTRUCTIONS = """You are Orizon's code-generation agent.

Given a user's intent, produce a self-contained SINGLE-FILE HTML artifact
that runs by saving to `index.html` and opening it in a browser.

Rules:
- Inline ALL CSS inside a <style> tag in <head>. No external stylesheets.
- Inline ALL JavaScript inside a <script> tag before </body>. No CDNs, no imports.
- No build step, no frameworks that require compilation.
- Use modern vanilla JS (ES2020+). DOM APIs only.
- Default to a tasteful DARK UI (deep bg, neon violet/cyan accents) unless the
  user asks for something else. Rounded corners, subtle shadows, mono font for
  numeric displays.
- Make it actually work: buttons should be wired, calculations should be correct,
  timers should tick, games should play. Not a mockup.
- Keep it under ~250 lines.

OUTPUT:
Return a CodeArtifact with:
- `title`: short product-style name, e.g. "Calculator".
- `summary`: one sentence describing what it does.
- `files`: a single entry {path: "index.html", language: "html", content: <full HTML>}.
- `entry`: "index.html".
- `preview_html`: exact same string as files[0].content.
"""


class CodeGen(Worker):
    id = "agt_11c0"
    name = "code.gen"
    real = True

    def __init__(self) -> None:
        self._agent = Agent(
            name="code.gen",
            model=OpenAIChat(id=settings.worker_model, api_key=settings.openai_api_key),
            instructions=INSTRUCTIONS,
            output_schema=CodeArtifact,
        )

    async def run(self, intent: str, rationale: str) -> dict[str, Any]:
        prompt = f"INTENT: {intent}\nRATIONALE: {rationale}\n\nReturn the CodeArtifact."
        result = await self._agent.arun(prompt)
        out: CodeArtifact = result.content  # type: ignore[assignment]

        # If the model forgot to populate preview_html, fall back to entry file content.
        preview = out.preview_html
        if not preview.strip():
            entry_file = next((f for f in out.files if f.path == out.entry), out.files[0])
            preview = entry_file.content

        artifact = {
            "title": out.title,
            "summary": out.summary,
            "files": [f.model_dump() for f in out.files],
            "entry": out.entry,
            "preview_html": preview,
        }
        return {
            "summary": out.title + " — " + out.summary,
            "artifact": artifact,
            "counts": {"files": len(out.files), "bytes": sum(len(f.content) for f in out.files)},
        }
