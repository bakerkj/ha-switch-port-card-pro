# Copyright (c) 2025 partach (original switch_port_card_pro)
# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu> (modifications)
# SPDX-License-Identifier: MIT
"""Early-warning guard against Home Assistant API drift.

This integration leans on a few HA public APIs whose shape we depend on. The
ha-dev-compat workflow runs this file against HA's `dev` branch weekly; a failure
here means upstream changed something we use — not that this branch is broken.
Keep these assertions tight and few.
"""

import inspect


def test_async_update_device_new_connections() -> None:
    """Port-to-device MAC linking reconciles via new_connections=."""
    from homeassistant.helpers import device_registry as dr

    assert (
        "new_connections"
        in inspect.signature(dr.DeviceRegistry.async_update_device).parameters
    )


def test_format_mac_and_connection_constant() -> None:
    """We stamp (CONNECTION_NETWORK_MAC, format_mac(mac)) onto port devices."""
    from homeassistant.helpers import device_registry as dr

    assert callable(dr.format_mac)
    assert list(inspect.signature(dr.format_mac).parameters)[:1] == ["mac"]
    assert dr.CONNECTION_NETWORK_MAC == "mac"


def test_device_info_has_connections() -> None:
    """Per-port DeviceInfo carries the client MAC in `connections`."""
    from homeassistant.helpers.device_registry import DeviceInfo

    assert "connections" in DeviceInfo.__annotations__


def test_data_update_coordinator_api() -> None:
    """The SNMP coordinator subclasses DataUpdateCoordinator and uses these."""
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

    for method in (
        "async_config_entry_first_refresh",
        "async_request_refresh",
        "async_set_updated_data",
    ):
        assert hasattr(DataUpdateCoordinator, method)
    params = list(inspect.signature(DataUpdateCoordinator.__init__).parameters)
    for expected in ("hass", "logger", "name", "update_interval"):
        assert expected in params


def test_store_persistence_api() -> None:
    """Managed state is persisted through Store."""
    from homeassistant.helpers.storage import Store

    for method in ("async_load", "async_save", "async_delay_save"):
        assert hasattr(Store, method)


def test_sensor_entity_api() -> None:
    """Per-port sensors expose native_value and standard state classes."""
    from homeassistant.components.sensor import SensorEntity, SensorStateClass

    assert hasattr(SensorEntity, "native_value")
    assert SensorStateClass.MEASUREMENT.value == "measurement"
