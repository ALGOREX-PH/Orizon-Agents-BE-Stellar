"""Pydantic schemas for curated demo kits.

A DemoKit is a hand-tuned specification that short-circuits the orchestrator
LLM for high-signal demo prompts (tetris, calculator, snake, pomodoro). It
feeds a deterministic 6-step plan with a guaranteed-quality artifact.
"""
from __future__ import annotations

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

    def feature_brief(self) -> str:
        return "\n".join(f"- {f.label}: {f.detail}" for f in self.features)

    def critic_block(self) -> str:
        return "\n".join(f"- {c}" for c in self.critic_checklist)
