"""Log-correlation observability: records emitted while a request is in
flight carry the request id injected by RequestIdLogFilter, and the access
line includes the resolved client key."""
from __future__ import annotations

import logging


def test_log_record_during_request_carries_request_id(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.security"):
        r = client.get("/api/agents", headers={"X-Request-ID": "caplog-rid-7"})
    assert r.status_code == 200

    access = [
        rec
        for rec in caplog.records
        if rec.name == "app.security" and "/api/agents" in rec.getMessage()
    ]
    assert access, "expected an access log record for the request"
    # RequestIdLogFilter stamps the id from the request's context onto the
    # record, so service logs correlate with the X-Request-ID echoed to the
    # client.
    assert all(getattr(rec, "request_id", "-") == "caplog-rid-7" for rec in access)
    # The access line names the same client key the rate limiter buckets on.
    assert "client=" in access[-1].getMessage()
