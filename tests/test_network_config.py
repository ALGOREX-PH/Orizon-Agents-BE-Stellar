"""Tests for the network-aware stellar.expert explorer mapping."""
from __future__ import annotations

from app.config import settings
from app.stellar import client as sc


def test_explorer_network_is_testnet_by_default():
    saved = settings.stellar_network
    settings.stellar_network = "testnet"
    try:
        assert sc.explorer_network() == "testnet"
    finally:
        settings.stellar_network = saved


def test_explorer_network_maps_mainnet_to_public():
    saved = settings.stellar_network
    try:
        settings.stellar_network = "mainnet"
        assert sc.explorer_network() == "public"
        settings.stellar_network = "public"
        assert sc.explorer_network() == "public"
    finally:
        settings.stellar_network = saved


def test_to_jsonable_converts_scval_natives():
    from stellar_sdk import Address

    g = "GA7AI5TAJEZA27I666DSJC4MUJYBEWUYNNZWPU7R2ONA7IZQVO6R5OQV"
    native = {
        "owner": Address(g),
        "receipts": [b"\x00" * 16],
        "count": 3,
        "name": "Orizon Batch",
    }
    out = sc._to_jsonable(native)
    assert out["owner"] == g
    assert out["receipts"] == ["00" * 16]
    assert out["count"] == 3
    assert out["name"] == "Orizon Batch"
