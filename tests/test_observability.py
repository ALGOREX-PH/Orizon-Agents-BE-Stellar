"""Log-correlation observability: records emitted while a request is in
flight carry the request id injected by RequestIdLogFilter, and the access
line includes the resolved client key.

Also covers the Soroban RPC instrumentation in app/stellar/client.py — the
timing/outcome lines and, critically, their LEVELS: reads are high-volume
(twelve per metrics poll) so successes must stay off INFO, while slow and
failed calls must be loud.
"""

from __future__ import annotations

import logging

import pytest

from app.stellar import client as sc

RPC_LOGGER = "app.stellar.client"


def test_log_record_during_request_carries_request_id(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.security"):
        r = client.get("/api/agents", headers={"X-Request-ID": "caplog-rid-7"})
    assert r.status_code == 200

    access = [rec for rec in caplog.records if rec.name == "app.security" and "/api/agents" in rec.getMessage()]
    assert access, "expected an access log record for the request"
    # RequestIdLogFilter stamps the id from the request's context onto the
    # record, so service logs correlate with the X-Request-ID echoed to the
    # client.
    assert all(getattr(rec, "request_id", "-") == "caplog-rid-7" for rec in access)
    # The access line names the same client key the rate limiter buckets on.
    assert "client=" in access[-1].getMessage()


# ── Soroban RPC instrumentation ────────────────────────────────────────
class _FakeSimulation:
    error = None
    results: list = []


class _FakeServer:
    """Stand-in for SorobanServer — no sockets, no network."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.fail_on = fail_on

    def load_account(self, address):
        if self.fail_on == "load_account":
            raise RuntimeError("429 too many requests")
        from stellar_sdk import Account

        return Account(address, 1)

    def simulate_transaction(self, tx):
        if self.fail_on == "simulate":
            raise RuntimeError("rpc unreachable")
        return _FakeSimulation()


@pytest.fixture()
def fake_rpc(monkeypatch):
    """Point client._server() at a scriptable in-process fake."""

    def install(fail_on: str | None = None) -> _FakeServer:
        server = _FakeServer(fail_on)
        monkeypatch.setattr(sc, "_server", lambda **_kw: server)
        return server

    return install


def _rpc_lines(caplog, level: int) -> list[str]:
    return [rec.getMessage() for rec in caplog.records if rec.name == RPC_LOGGER and rec.levelno == level]


def test_simulate_read_logs_one_timed_line_per_call(fake_rpc, caplog):
    """A successful read emits exactly one aggregated line carrying the
    contract, the function, and BOTH round-trips' latencies."""
    fake_rpc()
    with caplog.at_level(logging.DEBUG, logger=RPC_LOGGER):
        assert sc.simulate_read(sc.contract_ids().agent_registry, "get", [sc.sym("a1")]) is None

    debug = _rpc_lines(caplog, logging.DEBUG)
    assert len(debug) == 1, debug
    line = debug[0]
    assert "read agent_registry.get ok in" in line
    assert "load_ms=" in line and "sim_ms=" in line


def test_successful_read_never_logs_at_info(fake_rpc, caplog):
    """Volume guard: the metrics poll fans out twelve reads at a time, so a
    success must not reach INFO (the level production actually runs at)."""
    fake_rpc()
    with caplog.at_level(logging.DEBUG, logger=RPC_LOGGER):
        for _ in range(3):
            sc.simulate_read(sc.contract_ids().agent_registry, "get", [sc.sym("a1")])

    assert not [rec for rec in caplog.records if rec.name == RPC_LOGGER and rec.levelno >= logging.INFO]


def test_failed_read_logs_error_naming_the_stage(fake_rpc, caplog):
    fake_rpc(fail_on="load_account")
    with caplog.at_level(logging.DEBUG, logger=RPC_LOGGER), pytest.raises(RuntimeError):
        sc.simulate_read(sc.contract_ids().agent_registry, "get", [])

    errors = _rpc_lines(caplog, logging.ERROR)
    assert len(errors) == 1, errors
    # Which hop died, and why — the whole point of the instrumentation.
    assert "read agent_registry.get failed in" in errors[0]
    assert "stage=load_account" in errors[0]
    assert "429 too many requests" in errors[0]


def test_read_over_slow_threshold_logs_warning(caplog):
    """A throttled RPC is the precursor to executor saturation, so it is a
    WARNING even though the call ultimately succeeded."""
    with caplog.at_level(logging.DEBUG, logger=RPC_LOGGER):
        sc._log_rpc("read", "agent_registry.get", sc.SLOW_READ_MS + 1, {}, slow_ms=sc.SLOW_READ_MS)
        sc._log_rpc("read", "agent_registry.get", sc.SLOW_READ_MS - 1, {}, slow_ms=sc.SLOW_READ_MS)

    assert len(_rpc_lines(caplog, logging.WARNING)) == 1
    assert len(_rpc_lines(caplog, logging.DEBUG)) == 1


def test_submit_success_logs_at_info(caplog):
    """Money-path submits are rare and each moves value — worth an INFO line."""
    with caplog.at_level(logging.DEBUG, logger=RPC_LOGGER):
        sc._log_rpc("submit", "payment_escrow.charge", 12.0, {"tx": "abc"}, slow_ms=sc.SLOW_SUBMIT_MS, notable=True)

    info = _rpc_lines(caplog, logging.INFO)
    assert len(info) == 1
    assert "submit payment_escrow.charge ok in" in info[0]
    assert "tx=abc" in info[0]


def test_envelope_identity_never_leaks_the_xdr():
    """The log label for a signed envelope is derived, public data only."""
    from stellar_sdk import Account, Keypair, Network, TransactionBuilder

    kp = Keypair.random()
    tx = (
        TransactionBuilder(
            source_account=Account(kp.public_key, 1),
            network_passphrase=Network.TESTNET_NETWORK_PASSPHRASE,
            base_fee=100,
        )
        .append_bump_sequence_op(2)
        .set_timeout(30)
        .build()
    )
    tx.sign(kp)
    xdr = tx.to_xdr()

    tx_hash, source = sc.envelope_identity(xdr)
    assert source == kp.public_key
    assert len(tx_hash) == 64
    assert tx_hash not in xdr and source not in xdr
    # Undecodable input must degrade to placeholders, never raise.
    assert sc.envelope_identity("not-xdr") == ("unparseable", "unknown")


def test_diagnostic_decode_failures_are_reported_not_swallowed():
    """`except Exception: continue` used to drop these silently; the count is
    now folded into the summary the caller logs and returns."""

    class _Status:
        diagnostic_events_xdr = ["not-a-diagnostic-event", "also-garbage"]
        result_xdr = None

    summary = sc._extract_diagnostics(_Status())
    assert "2 undecodable diagnostic event(s)" in summary
