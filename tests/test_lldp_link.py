# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# SPDX-License-Identifier: MIT
"""LLDP neighbour linking: chassis-id parsing, LLDP-first selection, reconcile.

Covers the switch-side of the AP/switch link:
  * _chassis_id_to_mac  -- turn the ``0x<hex>`` OctetString the SNMP layer
    renders into a MAC, and reject anything that is not a 6-octet MAC.
  * _select_port_link_macs -- the LLDP-neighbour-wins-over-FDB precedence that
    keeps an AP-uplink port linked to the AP alone, never its wifi clients.
  * _desired_mac_connections -- the link_macs set (with client_mac back-compat).
  * _update_port_device_info -- stamping a *set* of MACs onto the port device,
    replacing/pruning against a real device registry.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.switch_port_card_pro.const import DOMAIN
from custom_components.switch_port_card_pro.sensor import (
    PortStatusSensor,
    SwitchPortPerPortBaseEntity,
    _chassis_id_to_mac,
    _select_port_link_macs,
)

_HOST = "switch.example.org"
_PORT = 5
_AP_MAC = "d0:d3:e0:c6:53:46"  # a real Aruba AP chassis MAC from the fleet
_CLIENT_A = "aa:bb:cc:dd:ee:01"
_CLIENT_B = "aa:bb:cc:dd:ee:02"


# ── _chassis_id_to_mac ────────────────────────────────────────────────────────


def test_chassis_id_hex_octetstring_becomes_mac() -> None:
    assert _chassis_id_to_mac("0xd0d3e0c65346") == _AP_MAC


def test_chassis_id_non_hex_subtypes_are_rejected() -> None:
    # a system name (subtype 5), a network address, an odd length -> not a MAC
    assert _chassis_id_to_mac("switch-0.keneli.org") is None
    assert _chassis_id_to_mac("0xdeadbeef") is None  # 4 octets, not 6
    assert _chassis_id_to_mac("0xZZZZZZZZZZZZ") is None  # right length, not hex
    assert _chassis_id_to_mac("") is None


# ── _select_port_link_macs (LLDP-first) ───────────────────────────────────────


def test_lldp_neighbour_wins_over_fdb() -> None:
    # The whole point: an AP uplink whose FDB also shows clients links the AP.
    assert _select_port_link_macs({_AP_MAC}, {_CLIENT_A, _CLIENT_B}) == [_AP_MAC]


def test_fdb_used_only_without_a_neighbour() -> None:
    assert _select_port_link_macs(set(), {_CLIENT_B, _CLIENT_A}) == [
        _CLIENT_A,
        _CLIENT_B,
    ]


def test_no_neighbour_no_clients_is_empty() -> None:
    assert _select_port_link_macs(set(), set()) == []


# ── _desired_mac_connections (link_macs set + client_mac back-compat) ──────────


def _conn(mac: str) -> tuple[str, str]:
    return (dr.CONNECTION_NETWORK_MAC, dr.format_mac(mac))


def test_desired_connections_from_link_macs_set() -> None:
    got = SwitchPortPerPortBaseEntity._desired_mac_connections(
        {"link_macs": [_AP_MAC, _CLIENT_A]}
    )
    assert got == {_conn(_AP_MAC), _conn(_CLIENT_A)}


def test_empty_link_macs_overrides_a_stale_client_mac() -> None:
    # link_macs present (LLDP path decided "nothing") wins over any client_mac.
    got = SwitchPortPerPortBaseEntity._desired_mac_connections(
        {"link_macs": [], "client_mac": _CLIENT_A}
    )
    assert got == set()


def test_client_mac_used_when_link_macs_absent() -> None:
    # Older coordinator data / fixtures without link_macs still link.
    got = SwitchPortPerPortBaseEntity._desired_mac_connections(
        {"client_mac": _CLIENT_A}
    )
    assert got == {_conn(_CLIENT_A)}


# ── reconcile against a real registry ─────────────────────────────────────────


def _coordinator(link_macs: list[str]) -> Any:
    data = SimpleNamespace(
        ports={str(_PORT): {"name": "uplink", "link_macs": link_macs}},
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
    link_macs: list[str],
    initial_connections: set[tuple[str, str]],
) -> tuple[dr.DeviceRegistry, tuple[str, str], PortStatusSensor]:
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
    entity = PortStatusSensor(_coordinator(link_macs), entry.entry_id, _PORT)
    entity.hass = hass
    return reg, port_id, entity


async def test_reconcile_stamps_the_neighbour_mac(hass: HomeAssistant) -> None:
    reg, port_id, entity = await _setup(hass, [_AP_MAC], set())
    entity._update_port_device_info()
    device = reg.async_get_device(identifiers={port_id})
    assert device is not None
    assert _network_macs(device) == {dr.format_mac(_AP_MAC)}


async def test_reconcile_stamps_multiple_client_macs(hass: HomeAssistant) -> None:
    # max_clients_to_link = 2: a two-client port links both.
    reg, port_id, entity = await _setup(hass, [_CLIENT_A, _CLIENT_B], set())
    entity._update_port_device_info()
    device = reg.async_get_device(identifiers={port_id})
    assert device is not None
    assert _network_macs(device) == {
        dr.format_mac(_CLIENT_A),
        dr.format_mac(_CLIENT_B),
    }


async def test_reconcile_replaces_a_prior_link(hass: HomeAssistant) -> None:
    old = _conn(_CLIENT_A)
    reg, port_id, entity = await _setup(hass, [_AP_MAC], {old})
    entity._update_port_device_info()
    device = reg.async_get_device(identifiers={port_id})
    assert device is not None
    assert _network_macs(device) == {dr.format_mac(_AP_MAC)}


async def test_reconcile_prunes_when_link_set_empties(hass: HomeAssistant) -> None:
    old = _conn(_AP_MAC)
    reg, port_id, entity = await _setup(hass, [], {old})
    entity._update_port_device_info()
    device = reg.async_get_device(identifiers={port_id})
    assert device is not None
    assert _network_macs(device) == set()


async def test_reconcile_leaves_non_mac_connections_untouched(
    hass: HomeAssistant,
) -> None:
    keep = (dr.CONNECTION_UPNP, "uuid:switch-port-card-pro-test")
    reg, port_id, entity = await _setup(hass, [_AP_MAC], {keep})
    entity._update_port_device_info()
    device = reg.async_get_device(identifiers={port_id})
    assert device is not None
    assert _network_macs(device) == {dr.format_mac(_AP_MAC)}
    assert keep in device.connections
