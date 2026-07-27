"""The money-movement API must document real response schemas in OpenAPI,
not bare {} objects."""
from __future__ import annotations

import pytest

from app.main import app

SAMPLES = [
    ("/api/pdax/trade/price", "get"),
    ("/api/pdax/trade/order", "post"),
    ("/api/pdax/trade/orders", "get"),
    ("/api/pdax/balances", "get"),
    ("/api/pdax/fiat/deposit", "post"),
    ("/api/pdax/fiat/withdraw", "post"),
    ("/api/pdax/crypto/withdraw", "post"),
    ("/api/pdax/ramp/onramp", "post"),
    ("/api/pdax/ramp/estimate", "post"),
    ("/api/pdax/ramp/{ramp_id}", "get"),
]


@pytest.mark.parametrize(("path", "method"), SAMPLES)
def test_pdax_routes_document_response_schema(path, method):
    spec = app.openapi()
    op = spec["paths"][path][method]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    # A typed response is a $ref to a named component model, never {}.
    assert "$ref" in schema, f"{method.upper()} {path} documents no response model"
    name = schema["$ref"].rsplit("/", 1)[-1]
    component = spec["components"]["schemas"][name]
    assert component.get("properties"), f"{name} has no properties"
