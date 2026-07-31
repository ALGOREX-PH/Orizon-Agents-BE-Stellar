"""The X-Forwarded-For trust boundary: which entry of the chain becomes the
rate-limit bucket and the access log's `client=`.

`TRUSTED_PROXY_HOPS` is the only knob, it cannot be inferred from outside the
deployment, and both ways of setting it wrong are silent — too low and every
visitor shares one global budget, too high and any caller can mint a fresh
bucket per request. These tests pin the shipped default (unchanged behaviour),
the resolution for each tuned value, and that a malformed or over-short chain
degrades toward the safe side rather than toward a bypass.
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.config import settings
from app.security import CHAIN_TOO_SHORT_KEY, RateLimitMiddleware, client_key


def _scope(forwarded: str | None = None, peer: str | None = "127.0.0.1") -> dict:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode("latin-1")))
    scope: dict = {"type": "http", "headers": headers}
    if peer is not None:
        scope["client"] = (peer, 12345)
    return scope


# A plausible production chain: what the visitor sent, the visitor's own
# address as the first proxy saw it, Vercel's egress, then Render's edge.
CHAIN = "203.0.113.50, 198.51.100.7, 76.76.21.9, 10.201.3.4"


def test_default_setting_is_zero_hops():
    """The default must reproduce the pre-existing behaviour exactly, so that
    merging the setting changes nothing until it is deliberately tuned."""
    assert settings.trusted_proxy_hops == 0


def test_default_resolves_the_last_hop():
    assert client_key(_scope(CHAIN)) == "10.201.3.4"


@pytest.mark.parametrize(
    ("hops", "expected"),
    [
        (0, "10.201.3.4"),  # today: the entry our own edge appended
        (1, "76.76.21.9"),  # skip Render's edge
        (2, "198.51.100.7"),  # skip Render + Vercel — the real visitor
        (3, "203.0.113.50"),  # one hop too far: now caller-controlled
    ],
)
def test_each_hop_count_resolves_the_expected_entry(hops, expected):
    assert client_key(_scope(CHAIN), hops=hops) == expected


def test_hop_count_is_read_from_settings(monkeypatch):
    """The middleware passes no explicit hop count, so the live setting — not
    an import-time snapshot — is what production resolution follows."""
    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
    assert client_key(_scope(CHAIN)) == "198.51.100.7"


def test_spoofed_leading_entries_cannot_influence_the_key_at_the_default():
    """A caller controls everything to the LEFT of the address our edge saw.
    At the default they may rotate it freely without ever moving the key."""
    keys = {
        client_key(_scope(f"{spoof}, 198.51.100.7, 76.76.21.9, 10.201.3.4"))
        for spoof in ("1.1.1.1", "2.2.2.2", "not-an-ip", "", "   ")
    }
    assert keys == {"10.201.3.4"}


def test_spoofed_entries_cannot_reach_the_key_at_the_intended_hop_count():
    """The same guarantee has to survive tuning: with two infrastructure hops
    trusted, injected entries stay to the left of the resolved visitor."""
    for spoof in ("1.1.1.1", "2.2.2.2", "9.9.9.9"):
        scope = _scope(f"{spoof}, 198.51.100.7, 76.76.21.9, 10.201.3.4")
        assert client_key(scope, hops=2) == "198.51.100.7"


def test_short_chain_resolves_to_the_sentinel_not_the_leftmost_entry():
    """Too-high a hop count must fail loudly-but-safely. Clamping to index 0
    would hand the key to the caller — the exact bypass the setting exists to
    avoid — so a chain with nothing left to resolve gets a literal instead."""
    assert client_key(_scope("198.51.100.7, 10.201.3.4"), hops=2) == CHAIN_TOO_SHORT_KEY
    assert client_key(_scope("10.201.3.4"), hops=5) == CHAIN_TOO_SHORT_KEY
    # The sentinel is not an address, so it can never collide with a client.
    assert CHAIN_TOO_SHORT_KEY.count(".") == 0


def test_malformed_chains_do_not_crash_and_fall_back_safely():
    # Empty entries are dropped rather than selected; a trailing comma must
    # not push resolution onto scope["client"], which uvicorn rewrites to the
    # caller-supplied LEFTMOST entry under --forwarded-allow-ips='*'.
    assert client_key(_scope("198.51.100.7, 10.201.3.4,")) == "10.201.3.4"
    assert client_key(_scope("198.51.100.7,,, 10.201.3.4")) == "10.201.3.4"
    assert client_key(_scope("  ,  198.51.100.7 ,  10.201.3.4  ")) == "10.201.3.4"
    # Nothing usable in the header at all → the transport peer, as before.
    assert client_key(_scope(" , , ")) == "127.0.0.1"
    assert client_key(_scope("")) == "127.0.0.1"
    # Header absent, and then no peer either.
    assert client_key(_scope(None)) == "127.0.0.1"
    assert client_key(_scope(None, peer=None)) == "unknown"
    # Non-address junk is keyed on verbatim rather than raising.
    assert client_key(_scope("a, b, ../../etc/passwd")) == "../../etc/passwd"


def test_negative_hop_count_is_floored_not_wrapped(monkeypatch):
    """A negative value would index from the caller-controlled end of the
    chain; it degrades to the default instead."""
    monkeypatch.setattr(settings, "trusted_proxy_hops", -3)
    assert client_key(_scope(CHAIN)) == "10.201.3.4"
    assert client_key(_scope(CHAIN), hops=-1) == "10.201.3.4"


def _limited_client(limit: int = 1) -> TestClient:
    async def ok(request):
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/hit", ok)])
    return TestClient(RateLimitMiddleware(inner, limit=limit, window_seconds=60))


def test_tuned_hops_give_distinct_visitors_distinct_buckets(monkeypatch):
    """The point of the setting: once the infrastructure hops are skipped, two
    visitors behind the same edge stop sharing one budget."""
    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
    limited = _limited_client()
    edge = "76.76.21.9, 10.201.3.4"
    assert limited.get("/hit", headers={"X-Forwarded-For": f"1.1.1.1, 198.51.100.7, {edge}"}).status_code == 200
    # Same visitor, rotated spoof prefix — still the same bucket.
    assert limited.get("/hit", headers={"X-Forwarded-For": f"2.2.2.2, 198.51.100.7, {edge}"}).status_code == 429
    # A different visitor behind the same edge gets its own.
    assert limited.get("/hit", headers={"X-Forwarded-For": f"1.1.1.1, 198.51.100.99, {edge}"}).status_code == 200


def test_untuned_default_leaves_one_shared_bucket(monkeypatch):
    """The problem this change makes configurable, pinned as behaviour: while
    the last entry is a constant our edge wrote, unrelated visitors share a
    single budget. Tuning TRUSTED_PROXY_HOPS is what fixes it."""
    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    limited = _limited_client()
    edge = "76.76.21.9, 10.201.3.4"
    assert limited.get("/hit", headers={"X-Forwarded-For": f"1.1.1.1, 198.51.100.7, {edge}"}).status_code == 200
    assert limited.get("/hit", headers={"X-Forwarded-For": f"2.2.2.2, 198.51.100.99, {edge}"}).status_code == 429
