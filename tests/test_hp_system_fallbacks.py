# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# SPDX-License-Identifier: MIT

"""Tests for the HP/Aruba cpu, memory and firmware fallbacks in a full poll.

When the user has not configured cpu/memory/firmware OIDs, a full poll on an
HP/Aruba (or unknown) switch fills them from HP's private OIDs. These tests pin
which fallbacks run, the values they produce, and that they are issued
concurrently rather than one after another.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.switch_port_card_pro.const import (
    HP_OID_CPU_REALTIME,
    HP_OID_FIRMWARE,
    HP_OID_MEMORY_TOTAL,
    HP_OID_MEMORY_USED,
)
from custom_components.switch_port_card_pro.sensor import SwitchPortCoordinator

_SENSOR = "custom_components.switch_port_card_pro.sensor"
_HP_OIDS = {
    HP_OID_CPU_REALTIME: "12",
    HP_OID_MEMORY_USED: "250",
    HP_OID_MEMORY_TOTAL: "1000",
    HP_OID_FIRMWARE: " WC.16.11.0001 ",
}
_CPU_OID = "1.3.6.1.4.1.99999.1.0"


class FakeSnmp:
    """Stand-in for the SNMP helpers: empty walks, canned GETs and bulk."""

    def __init__(self, bulk: dict[str, str] | None = None) -> None:
        self.bulk = bulk or {}
        self.hp_requested: list[str] = []
        self.hp_gate: asyncio.Event | None = None
        self.hp_expected = 0

    async def walk(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        return {}

    async def bulk_get(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        return dict(self.bulk)

    async def get(
        self, hass: Any, host: str, community: str, port: int, oid: str, **kw: Any
    ) -> str | None:
        if oid not in _HP_OIDS:
            return "100"  # sysUpTime
        self.hp_requested.append(oid)
        if self.hp_gate is not None:
            # Release only once every expected fallback is in flight: run one
            # after another, the first would wait forever.
            if len(self.hp_requested) == self.hp_expected:
                self.hp_gate.set()
            await self.hp_gate.wait()
        return _HP_OIDS[oid]


@pytest.fixture
def fake() -> Generator[FakeSnmp]:
    snmp = FakeSnmp()
    with (
        patch(f"{_SENSOR}.async_snmp_walk", side_effect=snmp.walk),
        patch(f"{_SENSOR}.async_snmp_bulk", side_effect=snmp.bulk_get),
        patch(f"{_SENSOR}.async_snmp_get", side_effect=snmp.get),
    ):
        yield snmp


def _coordinator(
    hass: HomeAssistant, manufacturer: str, system_oids: dict[str, str] | None = None
) -> SwitchPortCoordinator:
    coord = SwitchPortCoordinator(
        hass,
        "host",
        "public",
        161,
        [1],
        {},
        system_oids or {"uptime": "1.3.6.1.2.1.1.3.0"},
        "2c",
        False,
        30,
    )
    coord.manufacturer = manufacturer
    return coord


async def test_hp_fallbacks_fill_cpu_memory_firmware(
    hass: HomeAssistant, fake: FakeSnmp
) -> None:
    """Blank cpu/memory/firmware OIDs on an HP switch are filled from HP OIDs."""
    data = await _coordinator(hass, "HP")._full_update()

    assert sorted(fake.hp_requested) == sorted(_HP_OIDS)
    assert data.system["cpu"] == "12"
    assert data.system["memory"] == 25.0
    assert data.system["firmware"] == "WC.16.11.0001"


async def test_hp_fallbacks_are_issued_concurrently(
    hass: HomeAssistant, fake: FakeSnmp
) -> None:
    """All four fallback GETs are in flight together, not one after another."""
    fake.hp_gate = asyncio.Event()
    fake.hp_expected = len(_HP_OIDS)

    data = await asyncio.wait_for(_coordinator(hass, "Aruba")._full_update(), 5)

    assert len(fake.hp_requested) == len(_HP_OIDS)
    assert data.system["cpu"] == "12"


async def test_configured_value_skips_its_fallback(
    hass: HomeAssistant, fake: FakeSnmp
) -> None:
    """A cpu value from the user's own OID is kept; only the others fall back."""
    fake.bulk = {_CPU_OID: "7"}
    coord = _coordinator(hass, "HP", {"uptime": "1.3.6.1.2.1.1.3.0", "cpu": _CPU_OID})

    data = await coord._full_update()

    assert HP_OID_CPU_REALTIME not in fake.hp_requested
    assert sorted(fake.hp_requested) == sorted(
        [HP_OID_MEMORY_USED, HP_OID_MEMORY_TOTAL, HP_OID_FIRMWARE]
    )
    assert data.system["cpu"] == "7"
    assert data.system["memory"] == 25.0


async def test_non_hp_switch_skips_fallbacks(
    hass: HomeAssistant, fake: FakeSnmp
) -> None:
    """A known non-HP manufacturer never queries HP's private OIDs."""
    data = await _coordinator(hass, "Cisco")._full_update()

    assert fake.hp_requested == []
    assert data.system["cpu"] is None
    assert data.system["memory"] is None
    assert data.system["firmware"] is None
