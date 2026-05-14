"""Pydantic schemas for curated demo kits.

A DemoKit is a hand-tuned specification that short-circuits the orchestrator
LLM for high-signal demo prompts (tetris, calculator, snake, pomodoro). It
feeds a deterministic 6-step plan with a guaranteed-quality artifact.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class BrandSpec(BaseModel):
    name: str = Field(..., max_length=40)
    tagline: str = Field(..., max_length=120)
    audience: list[str] = Field(..., min_length=1, max_length=4)
    keywords: list[str] = Field(..., min_length=4, max_length=14)


class FeatureSpec(BaseModel):
    label: str = Field(..., max_length=60)
    detail: str = Field(..., max_length=240)


class PaletteSpec(BaseModel):
    bg: str
    surface: str
    surface_2: str
    border: str
    text: str
    muted: str
    primary: str
    accent: str
    danger: str

    def css_vars_block(self) -> str:
        return (
            ":root {\n"
            f"  --bg: {self.bg};\n"
            f"  --surface: {self.surface};\n"
            f"  --surface-2: {self.surface_2};\n"
            f"  --border: {self.border};\n"
            f"  --text: {self.text};\n"
            f"  --muted: {self.muted};\n"
            f"  --primary: {self.primary};\n"
            f"  --accent: {self.accent};\n"
            f"  --danger: {self.danger};\n"
            "}"
        )


class TypographySpec(BaseModel):
    family_ui: str         # e.g. "Inter, system-ui, sans-serif"
    family_display: str    # e.g. "JetBrains Mono, ui-monospace, monospace"
    base_size_px: int = 16
    scale: float = 1.25


class DemoKit(BaseModel):
    kit_id: str
    triggers: list[str] = Field(..., min_length=1)
    brand: BrandSpec
    features: list[FeatureSpec] = Field(..., min_length=4)
    palette: PaletteSpec
    typography: TypographySpec
    critic_checklist: list[str] = Field(..., min_length=4)
    code_gen_addendum: str
    expected_min_lines: int = 400
    # File under demo_kits/artifacts/ — when set, the pipeline serves this
    # baked HTML instead of asking the LLM to generate one.
    artifact_path: str | None = None

    def feature_brief(self) -> str:
        return "\n".join(f"- {f.label}: {f.detail}" for f in self.features)

    def critic_block(self) -> str:
        return "\n".join(f"- {c}" for c in self.critic_checklist)

    def load_artifact(self) -> dict[str, Any] | None:
        """Read the baked HTML file and return a CodeArtifact-shaped dict.

        Returns None if `artifact_path` is unset or the file doesn't exist.
        The returned dict matches the shape `code.gen` produces and is
        consumed by the trace UI's artifact iframe.
        """
        if not self.artifact_path:
            return None
        p = Path(__file__).parent / "artifacts" / self.artifact_path
        if not p.is_file():
            return None
        html = p.read_text(encoding="utf-8")
        return {
            "title": self.brand.name,
            "summary": self.brand.tagline,
            "files": [
                {"path": "index.html", "language": "html", "content": html}
            ],
            "entry": "index.html",
            "preview_html": html,
            "source": "baked",
            "kit_id": self.kit_id,
        }
