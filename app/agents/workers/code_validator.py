"""
Pure-Python validator for code.gen artifacts.

No LLM call — just fast regex/heuristic checks to catch obvious quality
issues before returning to the user. Feeds the critic with a precise list
of violations to fix.
"""
from __future__ import annotations

import re


_EXTERNAL_SCRIPT = re.compile(
    r'<script\b[^>]*\ssrc=["\'](?!data:|javascript:|#|/|\./|\.\./)([^"\']+)',
    re.IGNORECASE,
)
_EXTERNAL_STYLESHEET = re.compile(
    r'<link\b[^>]*\srel=["\']stylesheet["\'][^>]*\shref=["\'](?!data:|#|/|\./|\.\./)([^"\']+)',
    re.IGNORECASE,
)
_EXTERNAL_IMG = re.compile(
    r'<img\b[^>]*\ssrc=["\'](https?:)([^"\']+)',
    re.IGNORECASE,
)
_HAS_SCRIPT = re.compile(r'<script\b', re.IGNORECASE)
_HAS_HTML = re.compile(r'<html\b', re.IGNORECASE)
_HAS_HEAD = re.compile(r'<head\b', re.IGNORECASE)
_HAS_BODY = re.compile(r'<body\b', re.IGNORECASE)
_HAS_VIEWPORT = re.compile(
    r'<meta\b[^>]*\sname=["\']viewport["\']',
    re.IGNORECASE,
)


def validate_html(html: str) -> list[str]:
    """
    Return a list of human-readable violation strings. Empty list = clean.

    Each entry is short enough to paste straight into a prompt.
    """
    v: list[str] = []

    if not html or not html.strip():
        return ["artifact is empty"]

    # Size / depth
    line_count = html.count("\n") + 1
    if line_count < 200:
        v.append(f"under 200 lines ({line_count}) — feature-incomplete, add depth")

    # External asset violations (break sandbox, violate 'single-file' rule)
    for m in _EXTERNAL_SCRIPT.finditer(html):
        v.append(f'external <script src="{m.group(1)[:80]}"> — inline the JS instead')
    for m in _EXTERNAL_STYLESHEET.finditer(html):
        v.append(f'external <link stylesheet href="{m.group(1)[:80]}"> — inline the CSS')
    for m in _EXTERNAL_IMG.finditer(html):
        v.append(
            f'external <img src="{m.group(1)}{m.group(2)[:80]}"> — use inline SVG or data URI'
        )

    # Structural
    if not _HAS_HTML.search(html):
        v.append("missing <html> tag")
    if not _HAS_HEAD.search(html):
        v.append("missing <head> tag")
    if not _HAS_BODY.search(html):
        v.append("missing <body> tag")
    if not _HAS_VIEWPORT.search(html):
        v.append('missing <meta name="viewport" content="width=device-width,initial-scale=1">')
    if not _HAS_SCRIPT.search(html):
        v.append("no <script> block — artifact isn't interactive")

    return v
