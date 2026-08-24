# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# SPDX-License-Identifier: MIT

"""Tests for :mod:`custom_components.switch_port_card_pro.sensor`.

These exercise the tractable, high-value units of the sensor platform without
any network I/O:

* the module-level ``value_fn`` helpers (``_poe_power_watts``,
  ``_admin_status_value``, ``_link_speed_mbps``),
* the ``SwitchPortData`` dataclass,
* per-port entity computed outputs (``native_value``, ``available``, icons,
  ``extra_state_attributes``) across the ``PortSensorDescription`` set and both
  present-data and missing-data branches, and
* the aggregate/system sensors (bandwidth, PoE totals, CPU/memory/uptime,
  boot-time, hostname, firmware, temperature, fans).

The real async SNMP coordinator is never driven; instead a lightweight
``SimpleNamespace`` fake exposes only the attributes each entity reads.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from custom_components.switch_port_card_pro.sensor import (
    PORT_SENSOR_DESCRIPTIONS,
    BandwidthSensor,
    CustomValueSensor,
    FanStatusSensor,
    FirmwareSensor,
    PoEBudgetTotalSensor,
    PortAttributeSensor,
    PortInfoSensor,
    PortStatusSensor,
    SwitchPortData,
    SystemCpuSensor,
    SystemHostnameSensor,
    SystemMemorySensor,
    SystemStartTimeSensor,
    SystemUptimeSensor,
    TemperatureSensor,
    TotalPoESensor,
    _admin_status_value,
    _link_speed_mbps,
    _poe_power_watts,
)

# A fixed boot/last-change timestamp reused across cases.
_TS = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

# Descriptions keyed for direct lookup in the parametrized entity tests.
_DESC_BY_KEY = {d.key: d for d in PORT_SENSOR_DESCRIPTIONS}

# The entity's value_fn signature is (entity, port_dict); the helpers ignore the
# entity, so a typed-Any None stands in.
_NO_ENTITY: Any = cast(Any, None)


def _full_port() -> dict[str, Any]:
    """A representative fully-populated per-port data dict."""
    return {
        "status": "on",
        "speed": 1_000_000_000,  # bps (coordinator has already normalized)
        "rx": 1000,
        "tx": 2000,
        "rx_bps_live": 8000,
        "tx_bps_live": 16000,
        "name": "Uplink",
        "vlan": 10,
        "vlan_id_list": [10, 20],
        "poe_power": 15400,  # mW
        "poe_status": 3,
        "poe_class": 4,
        "port_custom": 42,
        "admin_status": "up",
        "in_errors": 1,
        "out_errors": 2,
        "in_discards": 3,
        "out_discards": 4,
        "last_change": _TS,
        "last_change_seconds": 100.0,
        "client_mac": "aa:bb:cc:dd:ee:ff",
    }


def _make_data(
    *,
    ports: dict[str, dict[str, Any]] | None = None,
    bandwidth_mbps: float = 12.5,
    system: dict[str, Any] | None = None,
) -> SwitchPortData:
    return SwitchPortData(
        ports=ports if ports is not None else {"1": _full_port()},
        bandwidth_mbps=bandwidth_mbps,
        system=system if system is not None else {},
    )


def _coordinator(
    *,
    data: SwitchPortData | None,
    host: str = "switch.local",
    port_mapping: dict[int, dict[str, Any]] | None = None,
    include_vlans: bool = True,
    base_oids: dict[str, str] | None = None,
    manufacturer: str = "Aruba",
    last_update_success: bool = True,
) -> Any:
    """A stand-in coordinator exposing only what the entities read."""
    return SimpleNamespace(
        data=data,
        host=host,
        port_mapping=port_mapping if port_mapping is not None else {},
        include_vlans=include_vlans,
        base_oids=base_oids if base_oids is not None else {},
        manufacturer=manufacturer,
        device_name=None,
        last_update_success=last_update_success,
    )


# --- module-level value_fn helpers -----------------------------------------


@pytest.mark.parametrize(
    ("poe_power", "expected"),
    [
        (15400, 15.4),
        (7000, 7.0),
        (1, 0.0),  # round(0.001, 2) -> 0.0
        (0, 0.0),  # falsy -> 0.0 branch
    ],
)
def test_poe_power_watts(poe_power: int, expected: float) -> None:
    assert _poe_power_watts(_NO_ENTITY, {"poe_power": poe_power}) == expected


def test_poe_power_watts_missing_key() -> None:
    assert _poe_power_watts(_NO_ENTITY, {}) == 0.0


@pytest.mark.parametrize(
    ("admin", "expected"),
    [("up", "up"), ("down", "down"), (None, None)],
)
def test_admin_status_value(admin: str | None, expected: str | None) -> None:
    assert _admin_status_value(_NO_ENTITY, {"admin_status": admin}) == expected


def test_admin_status_value_missing_key() -> None:
    assert _admin_status_value(_NO_ENTITY, {}) is None


@pytest.mark.parametrize(
    ("speed_bps", "expected_mbps"),
    [
        (1_000_000_000, 1000),
        (100_000_000, 100),
        (2_500_000_000, 2500),
        (0, 0),
    ],
)
def test_link_speed_mbps(speed_bps: int, expected_mbps: int) -> None:
    assert _link_speed_mbps(_NO_ENTITY, {"speed": speed_bps}) == expected_mbps


def test_link_speed_mbps_missing_key() -> None:
    assert _link_speed_mbps(_NO_ENTITY, {}) == 0


# --- SwitchPortData dataclass ----------------------------------------------


def test_switch_port_data_construction() -> None:
    ports = {"1": {"status": "on"}}
    system = {"hostname": "sw1"}
    data = SwitchPortData(ports=ports, bandwidth_mbps=3.5, system=system)
    assert data.ports is ports
    assert data.bandwidth_mbps == 3.5
    assert data.system is system


# --- per-port PortAttributeSensor computed outputs -------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("link_speed", 1000),
        ("rx_rate", 8000),
        ("tx_rate", 16000),
        ("rx_bytes", 1000),
        ("tx_bytes", 2000),
        ("in_errors", 1),
        ("out_errors", 2),
        ("in_discards", 3),
        ("out_discards", 4),
        ("admin_status", "up"),
        ("last_change", _TS),
        ("port_name", "Uplink"),
        ("port_custom", 42),
        ("vlan_id", 10),
        ("poe_power", 15.4),
        ("poe_class", 4),
        ("poe_enabled", "on"),
    ],
)
def test_port_attribute_native_value_present(key: str, expected: Any) -> None:
    coordinator = _coordinator(data=_make_data())
    sensor = PortAttributeSensor(coordinator, "entry1", 1, _DESC_BY_KEY[key])
    assert sensor.native_value == expected


def test_port_attribute_poe_enabled_off_branch() -> None:
    port = _full_port()
    port["poe_status"] = 1  # not 3 -> "off"
    coordinator = _coordinator(data=_make_data(ports={"1": port}))
    sensor = PortAttributeSensor(coordinator, "entry1", 1, _DESC_BY_KEY["poe_enabled"])
    assert sensor.native_value == "off"


@pytest.mark.parametrize("key", ["link_speed", "rx_rate", "poe_power", "admin_status"])
def test_port_attribute_native_value_missing_data(key: str) -> None:
    # No data for this port -> _port_data() empty -> native_value None.
    coordinator = _coordinator(data=_make_data(ports={}))
    sensor = PortAttributeSensor(coordinator, "entry1", 1, _DESC_BY_KEY[key])
    assert sensor.native_value is None


def test_port_attribute_native_value_no_coordinator_data() -> None:
    coordinator = _coordinator(data=None)
    sensor = PortAttributeSensor(coordinator, "entry1", 1, _DESC_BY_KEY["rx_rate"])
    assert sensor.native_value is None


def test_port_attribute_description_metadata_applied() -> None:
    coordinator = _coordinator(data=_make_data())
    desc = _DESC_BY_KEY["poe_power"]
    sensor = PortAttributeSensor(coordinator, "entry1", 1, desc)
    assert sensor._attr_native_unit_of_measurement == "W"
    assert sensor._attr_device_class == desc.device_class
    assert sensor._attr_state_class == desc.state_class
    assert sensor._attr_icon == "mdi:lightning-bolt"
    assert sensor._attr_suggested_display_precision == 1
    # enabled_default override wins when supplied.
    overridden = PortAttributeSensor(
        coordinator, "entry1", 1, desc, enabled_default=True
    )
    assert overridden._attr_entity_registry_enabled_default is True
    # falls back to the description's own default otherwise.
    assert sensor._attr_entity_registry_enabled_default == desc.enabled_default


def test_port_attribute_available() -> None:
    sensor = PortAttributeSensor(
        _coordinator(data=_make_data()), "entry1", 1, _DESC_BY_KEY["rx_rate"]
    )
    assert sensor.available is True
    sensor_no_data = PortAttributeSensor(
        _coordinator(data=None), "entry1", 1, _DESC_BY_KEY["rx_rate"]
    )
    assert sensor_no_data.available is False
    sensor_stale = PortAttributeSensor(
        _coordinator(data=_make_data(), last_update_success=False),
        "entry1",
        1,
        _DESC_BY_KEY["rx_rate"],
    )
    assert sensor_stale.available is False


# --- PortStatusSensor -------------------------------------------------------


def test_port_status_sensor_on() -> None:
    sensor = PortStatusSensor(_coordinator(data=_make_data()), "entry1", 1)
    assert sensor.native_value == "on"
    assert sensor.icon == "mdi:lan-connect"


def test_port_status_sensor_off() -> None:
    port = _full_port()
    port["status"] = "off"
    sensor = PortStatusSensor(
        _coordinator(data=_make_data(ports={"1": port})), "entry1", 1
    )
    assert sensor.native_value == "off"
    assert sensor.icon == "mdi:lan-disconnect"


def test_port_status_sensor_missing() -> None:
    sensor = PortStatusSensor(_coordinator(data=_make_data(ports={})), "entry1", 1)
    assert sensor.native_value == ""
    assert sensor.icon == "mdi:lan-disconnect"


# --- PortInfoSensor ---------------------------------------------------------


def test_port_info_sensor_native_value() -> None:
    sensor = PortInfoSensor(_coordinator(data=_make_data()), "entry1", 1)
    assert sensor.native_value == "Uplink"


def test_port_info_sensor_native_value_fallback() -> None:
    sensor = PortInfoSensor(_coordinator(data=_make_data(ports={})), "entry1", 1)
    assert sensor.native_value == "Port 1"


def test_port_info_sensor_extra_state_attributes() -> None:
    port_mapping = {
        1: {
            "if_index": 1,
            "is_sfp": False,
            "is_copper": True,
            "if_descr": "GigabitEthernet1",
        }
    }
    coordinator = _coordinator(
        data=_make_data(),
        port_mapping=port_mapping,
        include_vlans=True,
    )
    sensor = PortInfoSensor(coordinator, "entry1", 1)
    attrs = sensor.extra_state_attributes
    assert attrs["port_name"] == "Uplink"
    assert attrs["speed_bps"] == 1_000_000_000
    assert attrs["rx_bps"] == 8000  # 1000 bytes * 8
    assert attrs["tx_bps"] == 16000  # 2000 bytes * 8
    assert attrs["rx_bps_live"] == 8000
    assert attrs["tx_bps_live"] == 16000
    assert attrs["is_sfp"] is False
    assert attrs["is_copper"] is True
    assert attrs["interface"] == "GigabitEthernet1"
    assert attrs["custom"] == 42
    assert attrs["admin_status"] == "up"
    assert attrs["in_errors"] == 1
    assert attrs["out_errors"] == 2
    assert attrs["in_discards"] == 3
    assert attrs["out_discards"] == 4
    assert attrs["last_change"] == _TS.isoformat()
    # VLAN section (include_vlans True and vlan present)
    assert attrs["vlan_id"] == 10
    assert attrs["vlan_id_list"] == [10, 20]
    # PoE section (poe_power > 0 triggers has_poe)
    assert attrs["poe_power_watts"] == 15.4
    assert attrs["poe_enabled"] is True
    assert attrs["poe_class"] == 4


def test_port_info_sensor_attributes_empty_when_no_port() -> None:
    sensor = PortInfoSensor(_coordinator(data=_make_data(ports={})), "entry1", 1)
    assert sensor.extra_state_attributes == {}


def test_port_info_sensor_no_vlan_no_poe() -> None:
    port = _full_port()
    port["vlan"] = None
    port["vlan_id_list"] = []
    port["poe_power"] = 0
    port["poe_status"] = 0
    port["last_change"] = None
    coordinator = _coordinator(
        data=_make_data(ports={"1": port}),
        include_vlans=True,
        base_oids={},  # no poe OIDs configured
    )
    sensor = PortInfoSensor(coordinator, "entry1", 1)
    attrs = sensor.extra_state_attributes
    assert "vlan_id" not in attrs
    assert "vlan_id_list" not in attrs
    assert "poe_power_watts" not in attrs
    assert attrs["last_change"] is None


def test_port_info_sensor_poe_from_configured_oid() -> None:
    # has_poe becomes True purely from a configured base_oid even with 0 power.
    port = _full_port()
    port["poe_power"] = 0
    port["poe_status"] = 0
    coordinator = _coordinator(
        data=_make_data(ports={"1": port}),
        base_oids={"poe_power": "1.2.3.4"},
    )
    sensor = PortInfoSensor(coordinator, "entry1", 1)
    attrs = sensor.extra_state_attributes
    assert attrs["poe_power_watts"] == 0.0
    assert attrs["poe_enabled"] is False


# --- aggregate sensors ------------------------------------------------------


def test_total_poe_sensor() -> None:
    coordinator = _coordinator(data=_make_data(system={"poe_total_watts": 15.4}))
    assert TotalPoESensor(coordinator, "entry1").native_value == 15.4


def test_total_poe_sensor_none() -> None:
    coordinator = _coordinator(data=_make_data(system={"poe_total_watts": None}))
    assert TotalPoESensor(coordinator, "entry1").native_value is None


def test_total_poe_sensor_no_data() -> None:
    assert TotalPoESensor(_coordinator(data=None), "entry1").native_value == 0


def test_poe_budget_total_sensor() -> None:
    coordinator = _coordinator(data=_make_data(system={"poe_budget_watts": 370}))
    assert PoEBudgetTotalSensor(coordinator, "entry1").native_value == 370


def test_poe_budget_total_sensor_no_data() -> None:
    assert PoEBudgetTotalSensor(_coordinator(data=None), "entry1").native_value is None


def test_bandwidth_sensor() -> None:
    coordinator = _coordinator(data=_make_data(bandwidth_mbps=12.5))
    assert BandwidthSensor(coordinator, "entry1").native_value == 12.5


def test_bandwidth_sensor_no_data() -> None:
    assert BandwidthSensor(_coordinator(data=None), "entry1").native_value == 0


def test_firmware_sensor() -> None:
    coordinator = _coordinator(data=_make_data(system={"firmware": "1.2.3"}))
    assert FirmwareSensor(coordinator, "entry1").native_value == "1.2.3"


def test_firmware_sensor_no_data() -> None:
    assert FirmwareSensor(_coordinator(data=None), "entry1").native_value == ""


# --- system sensors ---------------------------------------------------------


def test_system_cpu_sensor() -> None:
    coordinator = _coordinator(data=_make_data(system={"cpu": "12"}))
    assert SystemCpuSensor(coordinator, "entry1").native_value == 12.0


def test_system_cpu_sensor_no_data() -> None:
    assert SystemCpuSensor(_coordinator(data=None), "entry1").native_value == 0


def test_custom_value_sensor() -> None:
    coordinator = _coordinator(data=_make_data(system={"custom": "hello"}))
    assert CustomValueSensor(coordinator, "entry1").native_value == "hello"


def test_custom_value_sensor_no_data() -> None:
    assert CustomValueSensor(_coordinator(data=None), "entry1").native_value == ""


def test_system_memory_sensor() -> None:
    coordinator = _coordinator(data=_make_data(system={"memory": 45.5}))
    assert SystemMemorySensor(coordinator, "entry1").native_value == 45.5


def test_system_memory_sensor_no_data() -> None:
    assert SystemMemorySensor(_coordinator(data=None), "entry1").native_value == 0


def test_system_uptime_sensor() -> None:
    coordinator = _coordinator(data=_make_data(system={"uptime": "123456"}))
    # hundredths of a second -> seconds
    assert SystemUptimeSensor(coordinator, "entry1").native_value == 1234


def test_system_uptime_sensor_no_data() -> None:
    assert SystemUptimeSensor(_coordinator(data=None), "entry1").native_value == 0


def test_system_start_time_sensor() -> None:
    coordinator = _coordinator(data=_make_data(system={"boot_time": _TS}))
    assert SystemStartTimeSensor(coordinator, "entry1").native_value == _TS


def test_system_start_time_sensor_no_data() -> None:
    assert SystemStartTimeSensor(_coordinator(data=None), "entry1").native_value is None


def test_system_hostname_sensor() -> None:
    coordinator = _coordinator(data=_make_data(system={"hostname": "sw1"}))
    assert SystemHostnameSensor(coordinator, "entry1").native_value == "sw1"


def test_system_hostname_sensor_no_data() -> None:
    assert SystemHostnameSensor(_coordinator(data=None), "entry1").native_value == ""


def test_temperature_sensor() -> None:
    coordinator = _coordinator(data=_make_data(system={"temperature_celsius": 42.5}))
    assert TemperatureSensor(coordinator, "entry1").native_value == 42.5


def test_temperature_sensor_no_data() -> None:
    assert TemperatureSensor(_coordinator(data=None), "entry1").native_value is None


# --- FanStatusSensor --------------------------------------------------------


def _fan(name: str, oper_status: int) -> dict[str, Any]:
    return {
        "entity_id": 1,
        "name": name,
        "oper_status": oper_status,
        "ok": oper_status == 1,
    }


def test_fan_status_all_ok() -> None:
    fans = [_fan("Fan 1", 1), _fan("Fan 2", 1)]
    sensor = FanStatusSensor(_coordinator(data=_make_data(system={"fans": fans})), "e")
    assert sensor.native_value == "ok"
    assert sensor.extra_state_attributes == {"Fan 1": "ok", "Fan 2": "ok"}


def test_fan_status_degraded() -> None:
    fans = [_fan("Fan 1", 1), _fan("Fan 2", 2)]
    sensor = FanStatusSensor(_coordinator(data=_make_data(system={"fans": fans})), "e")
    assert sensor.native_value == "degraded"
    assert sensor.extra_state_attributes == {"Fan 1": "ok", "Fan 2": "unavailable"}


def test_fan_status_unavailable() -> None:
    fans = [_fan("Fan 1", 2), _fan("Fan 2", 0)]
    sensor = FanStatusSensor(_coordinator(data=_make_data(system={"fans": fans})), "e")
    assert sensor.native_value == "unavailable"


def test_fan_status_empty() -> None:
    sensor = FanStatusSensor(_coordinator(data=_make_data(system={"fans": []})), "e")
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_fan_status_no_data() -> None:
    sensor = FanStatusSensor(_coordinator(data=None), "e")
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


# --- base entity availability + device info ---------------------------------


def test_base_entity_available_and_device_info() -> None:
    sensor = BandwidthSensor(_coordinator(data=_make_data()), "entry1")
    assert sensor.available is True
    # DeviceInfo built from coordinator host in __init__.
    assert sensor._attr_device_info is not None


def test_base_entity_available_stale() -> None:
    sensor = BandwidthSensor(
        _coordinator(data=_make_data(), last_update_success=False), "entry1"
    )
    assert sensor.available is False


def test_base_entity_available_attribute_error() -> None:
    # A coordinator missing last_update_success trips the AttributeError guard.
    broken: Any = SimpleNamespace(host="h", data=None)
    sensor = BandwidthSensor(_coordinator(data=None), "entry1")
    sensor.coordinator = broken
    assert sensor.available is False


# --- description registry sanity --------------------------------------------


def test_port_sensor_descriptions_flags() -> None:
    assert _DESC_BY_KEY["poe_power"].poe_only is True
    assert _DESC_BY_KEY["vlan_id"].vlan_only is True
    assert _DESC_BY_KEY["rx_rate"].poe_only is False
    # keys are unique
    keys = [d.key for d in PORT_SENSOR_DESCRIPTIONS]
    assert len(keys) == len(set(keys))
