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
