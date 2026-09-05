# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# SPDX-License-Identifier: MIT
"""Tests for _DeviceInfoReconciler: cache, no-op ticks, and external re-assert.

The reconciler must (a) not touch the device registry on a tick where nothing
changed — this is the whole point of the rewrite, to stop calling the
deprecated ``async_get_device`` (and its expensive ``report_usage`` stack walk)
every coordinator cycle — and (b) still correct an *external* edit to the
device, which it learns about via a device-registry-updated subscription that
invalidates the cache so the next tick re-asserts the desired state.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.switch_port_card_pro.const import DOMAIN
from custom_components.switch_port_card_pro.sensor import PortStatusSensor

_HOST = "switch.example.org"
_PORT = 7


def _coordinator(client_mac: str | None) -> Any:
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
    hass: HomeAssistant, client_mac: str | None
) -> tuple[dr.DeviceRegistry, tuple[str, str], PortStatusSensor]:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    reg = dr.async_get(hass)
    # Parent switch device — so the port's via_device_id resolves (and the
    # reconciler's cache primes) as it would in production.
    reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_{_HOST}")},
        name="sw1",
    )
    port_id = _port_identifier(entry.entry_id)
    reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={port_id},
        name=f"sw1 / Port {_PORT}",
        connections=set(),
    )
    entity = PortStatusSensor(_coordinator(client_mac), entry.entry_id, _PORT)
    entity.hass = hass
    return reg, port_id, entity


async def test_unchanged_tick_does_no_registry_write(
    hass: HomeAssistant, monkeypatch: Any
) -> None:
    """A second reconcile with identical data must not write the registry."""
    reg, port_id, entity = await _setup(hass, "AA:BB:CC:DD:EE:01")
    entity._reconcile_device_info()  # first: links the MAC (one write)

    calls: list[Any] = []
    real_update = reg.async_update_device

    def _counting_update(device_id: str, **kwargs: Any) -> Any:
        calls.append((device_id, kwargs))
        return real_update(device_id, **kwargs)

    monkeypatch.setattr(reg, "async_update_device", _counting_update)

    entity._reconcile_device_info()  # nothing changed
    entity._reconcile_device_info()  # still nothing changed

    assert calls == []  # zero registry writes on unchanged ticks
    device = reg.async_get_device_by_identifier(port_id, entity.entry_id)
    assert device is not None
    assert _network_macs(device) == {dr.format_mac("AA:BB:CC:DD:EE:01")}


async def test_external_edit_is_reasserted_after_invalidation(
    hass: HomeAssistant,
) -> None:
    """An external change invalidates the cache; the next tick re-asserts."""
    reg, port_id, entity = await _setup(hass, "AA:BB:CC:DD:EE:01")
    entity._reconcile_device_info()
    device = reg.async_get_device_by_identifier(port_id, entity.entry_id)
    assert device is not None
    want = dr.format_mac("AA:BB:CC:DD:EE:01")
    assert _network_macs(device) == {want}

    # Someone/something else stamps a rogue MAC on our device.
    rogue = (dr.CONNECTION_NETWORK_MAC, dr.format_mac("DE:AD:BE:EF:00:00"))
    reg.async_update_device(device.id, new_connections={rogue})
    rogue_dev = reg.async_get_device_by_identifier(port_id, entity.entry_id)
    assert rogue_dev is not None
    assert dr.format_mac("DE:AD:BE:EF:00:00") in _network_macs(rogue_dev)

    # Without invalidation the reconciler would consider itself up to date and
    # skip; the registry-updated subscription resets the cache so it re-asserts.
    entity._on_devreg_updated(SimpleNamespace(data={"action": "update"}))  # type: ignore[arg-type]
    entity._reconcile_device_info()

    device = reg.async_get_device_by_identifier(port_id, entity.entry_id)
    assert device is not None
    assert _network_macs(device) == {want}  # rogue MAC pruned, ours restored


async def test_removal_tears_down_subscription_and_resubscribes(
    hass: HomeAssistant,
) -> None:
    """A remove event must drop the id AND the dead subscription, so a later
    reconcile re-resolves and re-subscribes.

    Regression: previously only `_device_id` was cleared while `_unsub_devreg`
    kept the listener for the gone device; `_ensure_devreg_subscription`'s
    ``if self._unsub_devreg is None`` guard then never re-subscribed, so a
    device recreated under the same identifier was tracked but its external
    edits/removals were never detected again.
    """
    _reg, _port_id, entity = await _setup(hass, "AA:BB:CC:DD:EE:01")
    entity._reconcile_device_info()
    assert entity._device_id is not None
    assert entity._unsub_devreg is not None  # subscription established

    # Device removed: id cleared and the dead subscription torn down.
    entity._on_devreg_updated(SimpleNamespace(data={"action": "remove"}))  # type: ignore[arg-type]
    assert entity._device_id is None
    assert entity._unsub_devreg is None

    # A device with the same identifier is present again — the next reconcile
    # must re-resolve the id and establish a *fresh* subscription.
    entity._reconcile_device_info()
    assert entity._device_id is not None
    assert entity._unsub_devreg is not None
    entity._stop_devinfo_reconcile()


async def test_live_subscription_invalidates_and_reasserts(
    hass: HomeAssistant,
) -> None:
    """End-to-end: the real registry-updated subscription fires our handler.

    Unlike the tests above (which call ``_on_devreg_updated`` directly), this
    drives the actual ``async_track_device_registry_updated_event`` wiring set
    up by the reconciler: a genuine external ``async_update_device`` must reach
    our handler, invalidate the cache, and let the next tick re-assert.
    """
    reg, port_id, entity = await _setup(hass, "AA:BB:CC:DD:EE:01")
    # First reconcile links the MAC AND subscribes to registry updates.
    entity._reconcile_device_info()
    device = reg.async_get_device_by_identifier(port_id, entity.entry_id)
    assert device is not None
    assert entity._device_id is not None
    assert entity._applied_key is not None  # cache primed
    assert entity._unsub_devreg is not None  # subscription established

    # A genuine external edit — no direct handler call.
    rogue = (dr.CONNECTION_NETWORK_MAC, dr.format_mac("DE:AD:BE:EF:00:00"))
    reg.async_update_device(device.id, new_connections={rogue})
    await hass.async_block_till_done()  # let the event reach our subscriber

    # The live subscription must have invalidated the cache.
    assert entity._applied_key is None

    # Next tick re-asserts the desired MAC set, pruning the rogue.
    entity._reconcile_device_info()
    device = reg.async_get_device_by_identifier(port_id, entity.entry_id)
    assert device is not None
    assert _network_macs(device) == {dr.format_mac("AA:BB:CC:DD:EE:01")}

    # Cleanup the subscription (normally done in async_will_remove_from_hass).
    entity._stop_devinfo_reconcile()


async def test_transient_via_miss_preserves_existing_link(
    hass: HomeAssistant,
) -> None:
    """A parent that can't be resolved this tick must NOT clear a good link.

    Regression: when via_identifier resolution transiently missed (parent not
    yet in the registry), the reconciler wrote via_device_id=None, wiping an
    already-established parent link. It must instead leave the link and defer.
    """
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    reg = dr.async_get(hass)
    # An existing parent the port is already linked to.
    parent = reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "existing_parent")},
        name="Parent",
    )
    port_id = _port_identifier(entry.entry_id)
    port = reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={port_id},
        name=f"sw1 / Port {_PORT}",
        connections=set(),
    )
    reg.async_update_device(port.id, via_device_id=parent.id)
    # The port's real via target (the switch device) is deliberately NOT
    # created, so this tick's via_identifier resolution misses.
    entity = PortStatusSensor(_coordinator("AA:BB:CC:DD:EE:01"), entry.entry_id, _PORT)
    entity.hass = hass
    entity._reconcile_device_info()

    got = reg.async_get_device_by_identifier(port_id, entry.entry_id)
    assert got is not None
    assert got.via_device_id == parent.id  # existing link preserved, not cleared
    assert entity._applied_key is None  # via unresolved → will retry next tick
    entity._stop_devinfo_reconcile()


async def test_connection_collision_keeps_rename_and_retries(
    hass: HomeAssistant, monkeypatch: Any
) -> None:
    """A MAC-connection collision must not drop a bundled rename or strand.

    Regression: name/via/connections were one write, and the key was cached even
    when it raised — so a routine collision dropped the rename AND was never
    retried. Now scalar and connection writes are separate, and a failed write
    leaves the spec uncached so the next tick retries once the conflict clears.
    """
    reg, port_id, entity = await _setup(hass, "AA:BB:CC:DD:EE:01")
    real_update = reg.async_update_device

    def _flaky(device_id: str, **kwargs: Any) -> Any:
        if "new_connections" in kwargs:
            raise HomeAssistantError("MAC already on another device")
        return real_update(device_id, **kwargs)

    monkeypatch.setattr(reg, "async_update_device", _flaky)
    entity._reconcile_device_info()

    got = reg.async_get_device_by_identifier(port_id, entity.entry_id)
    assert got is not None
    assert got.name == f"sw1 / Port {_PORT} (camera)"  # rename applied anyway
    assert _network_macs(got) == set()  # connection write was rejected
    assert entity._applied_key is None  # not cached → will retry

    # Collision clears; the next tick must link the MAC and then cache.
    monkeypatch.setattr(reg, "async_update_device", real_update)
    entity._reconcile_device_info()
    got = reg.async_get_device_by_identifier(port_id, entity.entry_id)
    assert got is not None
    assert _network_macs(got) == {dr.format_mac("AA:BB:CC:DD:EE:01")}
    assert entity._applied_key is not None
    entity._stop_devinfo_reconcile()
