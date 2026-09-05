# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# SPDX-License-Identifier: MIT
"""Device-registry reconcile tests for port-to-device MAC linking.

Drives SwitchPortPerPortBaseEntity._reconcile_device_info against a real
device registry — the code path that stamps/prunes a port device's
CONNECTION_NETWORK_MAC. It must add the current single client's MAC, replace
(not accumulate) a changed one, prune it when the client goes away, and never
disturb connections it does not own.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.switch_port_card_pro.const import DOMAIN
from custom_components.switch_port_card_pro.sensor import PortStatusSensor

_HOST = "switch.example.org"
_PORT = 5


def _coordinator(client_mac: str | None) -> Any:
    """Minimal fake coordinator exposing only what the entity reads."""
    data = SimpleNamespace(
        ports={str(_PORT): {"name": "camera", "client_mac": client_mac}},
        system={"hostname": "sw1"},
    )
    return SimpleNamespace(
        host=_HOST,
        data=data,
        port_mapping={},
        manufacturer="TestVendor",
        device_name="sw1",
        last_update_success=True,
        async_add_listener=lambda _cb: lambda: None,
    )


def _port_identifier(entry_id: str) -> tuple[str, str]:
    return (DOMAIN, f"{entry_id}_{_HOST}_port_{_PORT}")


def _network_macs(device: dr.DeviceEntry) -> set[str]:
    return {v for t, v in device.connections if t == dr.CONNECTION_NETWORK_MAC}


async def _setup(
    hass: HomeAssistant,
    client_mac: str | None,
    initial_connections: set[tuple[str, str]],
) -> tuple[dr.DeviceRegistry, tuple[str, str], PortStatusSensor]:
    """Pre-create the port device, return (registry, identifier, entity)."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    reg = dr.async_get(hass)
    port_id = _port_identifier(entry.entry_id)
    reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={port_id},
        name=f"sw1 / Port {_PORT}",
        connections=initial_connections,
    )
    entity = PortStatusSensor(_coordinator(client_mac), entry.entry_id, _PORT)
    entity.hass = hass
    return reg, port_id, entity


async def test_first_update_links_client_mac(hass: HomeAssistant) -> None:
    reg, port_id, entity = await _setup(hass, "AA:BB:CC:DD:EE:01", set())
    entity._reconcile_device_info()
    device = reg.async_get_device_by_identifier(port_id, entity.entry_id)
    assert device is not None
    assert _network_macs(device) == {dr.format_mac("AA:BB:CC:DD:EE:01")}


async def test_changed_client_mac_replaces_not_accumulates(
    hass: HomeAssistant,
) -> None:
    old = (dr.CONNECTION_NETWORK_MAC, dr.format_mac("AA:BB:CC:DD:EE:01"))
    reg, port_id, entity = await _setup(hass, "AA:BB:CC:DD:EE:02", {old})
    entity._reconcile_device_info()
    device = reg.async_get_device_by_identifier(port_id, entity.entry_id)
    assert device is not None
    # exactly the new MAC — the old one must NOT linger
    assert _network_macs(device) == {dr.format_mac("AA:BB:CC:DD:EE:02")}


async def test_disappeared_client_mac_is_pruned(hass: HomeAssistant) -> None:
    old = (dr.CONNECTION_NETWORK_MAC, dr.format_mac("AA:BB:CC:DD:EE:01"))
    reg, port_id, entity = await _setup(hass, None, {old})
    entity._reconcile_device_info()
    device = reg.async_get_device_by_identifier(port_id, entity.entry_id)
    assert device is not None
    assert _network_macs(device) == set()


async def test_non_mac_connections_survive(hass: HomeAssistant) -> None:
    keep = (dr.CONNECTION_UPNP, "uuid:switch-port-card-pro-test")
    old = (dr.CONNECTION_NETWORK_MAC, dr.format_mac("AA:BB:CC:DD:EE:01"))
    reg, port_id, entity = await _setup(hass, "AA:BB:CC:DD:EE:02", {old, keep})
    entity._reconcile_device_info()
    device = reg.async_get_device_by_identifier(port_id, entity.entry_id)
    assert device is not None
    assert _network_macs(device) == {dr.format_mac("AA:BB:CC:DD:EE:02")}
    assert keep in device.connections  # non-MAC connection untouched


async def test_no_op_when_mac_already_current(hass: HomeAssistant) -> None:
    mac = dr.format_mac("AA:BB:CC:DD:EE:01")
    reg, port_id, entity = await _setup(
        hass, "AA:BB:CC:DD:EE:01", {(dr.CONNECTION_NETWORK_MAC, mac)}
    )
    entity._reconcile_device_info()
    device = reg.async_get_device_by_identifier(port_id, entity.entry_id)
    assert device is not None
    assert _network_macs(device) == {mac}
