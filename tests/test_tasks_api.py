"""API tests for the task routes: the polled list stays lightweight (no
artifact), the per-task and artifact routes still serve the full payload, and
`started` is a live relative age derived from `started_at` rather than a string
frozen at creation time.
"""

from __future__ import annotations

import time

import pytest

from app.main import app
from app.schemas import Task, humanize_age
from app.security import RateLimitMiddleware
from app.state import state

# Stand-in for a baked kit artifact: files[0].content plus a byte-identical
# preview_html, ~70 KB on the wire for one completed task.
_MARKER = "<!-- artifact-payload-marker -->"
_BIG_HTML = _MARKER + ("<p>x</p>" * 4_000)
_ARTIFACT = {
    "title": "Demo",
    "summary": "s",
    "entry": "index.html",
    "files": [{"path": "index.html", "language": "html", "content": _BIG_HTML}],
    "preview_html": _BIG_HTML,
}


def _clear_rate_limiter() -> None:
    """Drop the app-wide sliding-window hit table. The limiter instance lives
    for the whole pytest process, so this file's extra requests would otherwise
    eat into the shared per-minute budget and 429 later test files."""
    node = getattr(app, "middleware_stack", None)
    while node is not None and not isinstance(node, RateLimitMiddleware):
        node = getattr(node, "app", None)
    if node is not None:
        node._hits.clear()


@pytest.fixture(autouse=True)
def budget_neutral_rate_limit():
    _clear_rate_limiter()
    yield
    _clear_rate_limiter()


@pytest.fixture(autouse=True)
def clean_tasks():
    saved_tasks = dict(state.tasks)
    saved_order = list(state.task_order)
    state.tasks.clear()
    state.task_order.clear()
    yield
    state.tasks.clear()
    state.task_order.clear()
    state.tasks.update(saved_tasks)
    state.task_order.extend(saved_order)


def _seed(task_id: str = "tsk_list_shape") -> Task:
    task = Task(
        id=task_id,
        intent="build a demo page",
        agents=2,
        spent=0.25,
        status="complete",
        artifact=_ARTIFACT,
        charge_tx="charge123",
        proof_tx="proof456",
    )
    state.add_task(task)
    return task


# ── (a) the polled list never ships artifacts ───────────────────
def test_task_list_omits_the_artifact(client):
    task = _seed()
    r = client.get("/api/tasks")
    assert r.status_code == 200
    row = next(t for t in r.json() if t["id"] == task.id)
    assert "artifact" not in row
    # ...and not merely nulled out: no byte of the payload is on the wire.
    assert _MARKER not in r.text


def test_task_list_keeps_every_field_the_dashboard_renders(client):
    task = _seed()
    row = next(t for t in client.get("/api/tasks").json() if t["id"] == task.id)
    assert row["intent"] == "build a demo page"
    assert row["agents"] == 2
    assert row["spent"] == 0.25
    assert row["status"] == "complete"
    assert isinstance(row["started"], str)
    assert row["charge_tx"] == "charge123"
    assert row["proof_tx"] == "proof456"


def test_task_list_stays_small_with_many_completed_tasks(client):
    for i in range(20):
        _seed(f"tsk_bulk_{i:02d}")
    body = client.get("/api/tasks", params={"limit": 20}).content
    assert len(body) < len(_BIG_HTML), "the list is still shipping artifact-sized payloads"


def test_task_list_openapi_schema_has_no_artifact(client):
    schema = client.get("/openapi.json").json()
    ref = schema["paths"]["/api/tasks"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["items"]
    name = ref["$ref"].rsplit("/", 1)[-1]
    assert "artifact" not in schema["components"]["schemas"][name]["properties"]


# ── (b) the routes that must still serve it ─────────────────────
def test_single_task_route_still_returns_the_artifact(client):
    task = _seed()
    body = client.get(f"/api/tasks/{task.id}").json()
    assert body["artifact"] == _ARTIFACT


def test_artifact_route_still_returns_the_artifact(client):
    task = _seed()
    body = client.get(f"/api/tasks/{task.id}/artifact").json()
    assert body["artifact"] == _ARTIFACT
    assert body["charge_tx"] == "charge123"
    assert body["proof_tx"] == "proof456"


# ── (c) `started` is a live age, not a frozen string ────────────
def _aged(task_id: str, age_seconds: float) -> Task:
    task = Task(
        id=task_id,
        intent="build a demo page",
        agents=1,
        spent=0.0,
        status="complete",
        started_at=time.time() - age_seconds,
    )
    state.add_task(task)
    return task


@pytest.mark.parametrize(
    ("age_seconds", "expected"),
    [(0.0, "just now"), (9.5, "just now"), (30.0, "30s ago"), (125.0, "2m ago"), (7_200.0, "2h ago")],
)
def test_started_reflects_elapsed_time(client, age_seconds, expected):
    task = _aged("tsk_started_age", age_seconds)
    row = next(t for t in client.get("/api/tasks").json() if t["id"] == task.id)
    assert row["started"] == expected


def test_started_of_an_old_task_is_not_just_now(client):
    """The regression: `started` was written once at creation and never
    updated, so every row — including hours-old runs — read "just now"."""
    task = _aged("tsk_started_old", 5 * 3_600)
    row = next(t for t in client.get("/api/tasks").json() if t["id"] == task.id)
    assert row["started"] == "5h ago"
    assert row["started"] != "just now"


def test_started_at_is_served_as_a_machine_readable_timestamp(client):
    started_at = time.time() - 90.0
    state.add_task(Task(id="tsk_started_ts", intent="i", agents=1, spent=0.0, status="running", started_at=started_at))
    row = next(t for t in client.get("/api/tasks").json() if t["id"] == "tsk_started_ts")
    assert row["started_at"] == pytest.approx(started_at)


def test_started_is_derived_on_every_serialization():
    # Not stored: two dumps of the same instance, taken at different times,
    # disagree — which is exactly why the field can no longer go stale.
    task = Task(id="tsk_started_derived", intent="i", agents=1, spent=0.0, status="running")
    assert task.model_dump()["started"] == "just now"
    task.started_at -= 3_600
    assert task.model_dump()["started"] == "1h ago"


def test_started_survives_the_finalize_model_copy():
    task = Task(id="tsk_started_copy", intent="i", agents=1, spent=0.0, status="running")
    task.started_at -= 600
    finalized = task.model_copy(update={"status": "complete"})
    assert finalized.started == "10m ago"


def test_humanize_age_bands():
    assert humanize_age(-5.0) == "just now"  # clock skew
    assert humanize_age(59.9) == "59s ago"
    assert humanize_age(3_599.0) == "59m ago"
    assert humanize_age(86_399.0) == "23h ago"
    assert humanize_age(200_000.0) == "2d ago"
