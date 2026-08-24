# Copyright (c) 2025 partach (original switch_port_card_pro)
# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu> (modifications)
# SPDX-License-Identifier: MIT

"""Unit tests for the pure (non-I/O) helpers in ``snmp_helper``.

These exercise the classification/parsing logic that turns raw SNMP walk
output into physical-port metadata. The async SNMP functions are intentionally
not tested here (they require a live agent).
"""

from __future__ import annotations

import pytest
from puresnmp import V1, V2C
from x690.types import Integer, ObjectIdentifier, OctetString

from custom_components.switch_port_card_pro.const import (
    CONF_OID_IFHIGHSPEED,
    CONF_OID_IFSPEED,
    CONF_OID_IFTYPE,
)
from custom_components.switch_port_card_pro.snmp_helper import (
    _credentials,
    _detect_sfp_port,
    _extract_manufacturer,
    _generate_port_name,
    _get_interface_type,
    _get_port_speed,
    _is_physical_interface,
    _is_virtual_interface,
    _value_to_str,
)


# ── _value_to_str ────────────────────────────────────────────────────────────
def test_value_to_str_none() -> None:
    """None maps to the empty string."""
    assert _value_to_str(None) == ""


def test_value_to_str_empty_octetstring() -> None:
    """An empty OctetString is the empty string, not '0x'."""
    assert _value_to_str(OctetString(b"")) == ""


def test_value_to_str_printable_octetstring() -> None:
    """Printable ASCII bytes are decoded as text."""
    assert _value_to_str(OctetString(b"Port 1")) == "Port 1"


def test_value_to_str_space_is_printable() -> None:
    """0x20 (space) is inside the printable window and stays text."""
    assert _value_to_str(OctetString(b" ")) == " "


def test_value_to_str_binary_octetstring_is_hex() -> None:
    """Non-printable bytes become a 0x-prefixed hex string."""
    assert _value_to_str(OctetString(bytes([0x1C, 0x28, 0xAF]))) == "0x1c28af"


def test_value_to_str_del_byte_is_not_printable() -> None:
    """0x7F (DEL) is excluded by the < 0x7F bound, forcing hex output."""
    assert _value_to_str(OctetString(bytes([0x7F]))) == "0x7f"


def test_value_to_str_object_identifier() -> None:
    """An ObjectIdentifier stringifies to dotted-decimal."""
    oid = ObjectIdentifier("1.3.6.1.2.1.26.4.35")
    assert _value_to_str(oid) == "1.3.6.1.2.1.26.4.35"


def test_value_to_str_integer_unwraps_value() -> None:
    """Integer-like objects render their inner .value as decimal."""
    assert _value_to_str(Integer(42)) == "42"


def test_value_to_str_plain_int() -> None:
    """A bare int (no .value attribute) falls back to str()."""
    assert _value_to_str(100) == "100"


# ── _extract_manufacturer ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("sys_descr", "expected"),
    [
        ("", "Unknown"),
        ("Unknown", "Unknown"),
        ("H3C S3100-26C, Software Version 5.20", "H3C"),
        ("Aruba JL256A 2930F", "Aruba"),
        ("version 1.2.3", "Unknown"),
        ("Software Release build 9", "Unknown"),
        ("HARDWARE rev 2", "Unknown"),
    ],
)
def test_extract_manufacturer(sys_descr: str, expected: str) -> None:
    """First word wins unless it is a known non-manufacturer keyword."""
    assert _extract_manufacturer(sys_descr) == expected


# ── _is_virtual_interface ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "descr_lower",
    [
        "cpu interface",
        "link aggregate 1",
        "logical-int 5",
        "vlan10",
        "po1",
        "tunnel0",
        "lo",
        "br",
        "bond",
        "bridge",
        "virtual interface",
        "loopback0",
    ],
)
def test_is_virtual_interface_true(descr_lower: str) -> None:
    """Known virtual/aggregate/loopback descriptors are rejected."""
    assert _is_virtual_interface(descr_lower) is True


@pytest.mark.parametrize(
    "descr_lower",
    [
        "port 1",
        "gigabitethernet1/0/1",
        "eth0",
        "swp5",
        "a1",
    ],
)
def test_is_virtual_interface_false(descr_lower: str) -> None:
    """Real physical descriptors are not flagged virtual."""
    assert _is_virtual_interface(descr_lower) is False


def test_is_virtual_interface_lo_is_word_bounded() -> None:
    """'lo' matches only as a whole word, not inside 'slot'."""
    assert _is_virtual_interface("slot:1 port:2") is False


# ── _is_physical_interface ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("descr_lower", "descr_clean", "if_index", "expected"),
    [
        # Management / console ports are excluded.
        ("mgmt0", "mgmt0", 1, False),
        ("management interface", "management interface", 1, False),
        ("console", "console", 1, False),
        # Cisco management port GigabitEthernet0/0.
        ("gigabitethernet0/0", "GigabitEthernet0/0", 1, False),
        # Keyword-based physical acceptance.
        ("port 5", "Port 5", 5, True),
        ("eth3", "eth3", 3, True),
        ("swp10", "swp10", 10, True),
        ("sfp1", "SFP1", 1, True),
        # HP/Aruba uplink style A1 (single letter + digits).
        ("a1", "A1", 24, True),
        # slot:/port: form.
        ("slot:1 port:2", "Slot:1 Port:2", 2, True),
        # Something with no port indicators at all.
        ("random", "random", 5, False),
    ],
)
def test_is_physical_interface(
    descr_lower: str, descr_clean: str, if_index: int, expected: bool
) -> None:
    """Physical-port acceptance covers keyword, pattern, and exclusion paths."""
    # Regex-accept branches return a truthy re.Match rather than literal True,
    # matching how callers use the result (``if not is_likely_physical``).
    assert bool(_is_physical_interface(descr_lower, descr_clean, if_index)) is expected


def test_is_physical_interface_digit_low_index() -> None:
    """A purely numeric name with a low ifIndex is a real port."""
    assert _is_physical_interface("7", "7", 7) is True


def test_is_physical_interface_digit_high_index() -> None:
    """A purely numeric name with ifIndex >= 1000 is rejected."""
    assert _is_physical_interface("7", "7", 5000) is False


# ── _get_interface_type ──────────────────────────────────────────────────────
def test_get_interface_type_pretty_form() -> None:
    """The 'ethernetCsmacd(6)' pretty form yields the numeric 6."""
    data = {f"{CONF_OID_IFTYPE}.3": "ethernetCsmacd(6)"}
    assert _get_interface_type(data, 3) == 6


def test_get_interface_type_plain_numeric() -> None:
    """A bare numeric ifType parses directly."""
    data = {f"{CONF_OID_IFTYPE}.3": "6"}
    assert _get_interface_type(data, 3) == 6


def test_get_interface_type_missing_index() -> None:
    """No entry for the ifIndex returns 0."""
    data = {f"{CONF_OID_IFTYPE}.99": "6"}
    assert _get_interface_type(data, 3) == 0


def test_get_interface_type_unparseable() -> None:
    """A value that is neither pretty nor numeric returns 0."""
    data = {f"{CONF_OID_IFTYPE}.3": "garbage"}
    assert _get_interface_type(data, 3) == 0


# ── _detect_sfp_port ─────────────────────────────────────────────────────────
def test_detect_sfp_hp_uplink_name() -> None:
    """HP/Aruba A1-style uplink names are classified as SFP."""
    assert _detect_sfp_port(6, "a1", "Aruba") == (True, "hp_uplink_name")


def test_detect_sfp_hp_uplink_requires_hp_vendor() -> None:
    """The A1 shortcut only fires for HP-family manufacturers."""
    assert _detect_sfp_port(6, "a1", "Cisco") == (False, "default_copper")


def test_detect_sfp_netgear_10g_level() -> None:
    """Netgear's '10G - Level' descriptor is treated as SFP+."""
    assert _detect_sfp_port(6, "slot: 0 10g - level", "Netgear") == (
        True,
        "netgear_10g_sfp",
    )


def test_detect_sfp_cisco_module_slot() -> None:
    """A Cisco module slot (middle index > 0) is an SFP port."""
    assert _detect_sfp_port(6, "gigabithethernet1/1/1", "Cisco") == (
        True,
        "cisco_module_sfp",
    )


def test_detect_sfp_cisco_fixed_copper() -> None:
    """A Cisco fixed slot (middle index 0) is copper."""
    assert _detect_sfp_port(6, "gigabithethernet1/0/24", "Cisco") == (
        False,
        "cisco_fixed_copper",
    )


@pytest.mark.parametrize("if_type", [56, 171])
def test_detect_sfp_iftype_fiber(if_type: int) -> None:
    """fibreChannel (56) and POS (171) ifTypes are fiber."""
    assert _detect_sfp_port(if_type, "port 1", "Generic") == (True, "iftype_fiber")


@pytest.mark.parametrize(
    "descr_lower",
    ["sfp+ port", "10gbase-lr", "qsfp28", "fiber uplink", "40g link"],
)
def test_detect_sfp_name_keyword(descr_lower: str) -> None:
    """Fiber keywords in the description flag an SFP port."""
    assert _detect_sfp_port(6, descr_lower, "Generic") == (True, "name_keyword")


def test_detect_sfp_10gbase_t_is_copper() -> None:
    """10GBASE-T is copper and must not match the fiber keyword list."""
    assert _detect_sfp_port(6, "10gbase-t port", "Generic") == (
        False,
        "default_copper",
    )


def test_detect_sfp_default_copper() -> None:
    """A plain ethernet port defaults to copper."""
    assert _detect_sfp_port(6, "port 1", "Generic") == (False, "default_copper")


# ── _get_port_speed ──────────────────────────────────────────────────────────
def test_get_port_speed_prefers_high_speed() -> None:
    """ifHighSpeed (already in Mbps) is used verbatim when present."""
    high = {f"{CONF_OID_IFHIGHSPEED}.3": "1000"}
    low = {f"{CONF_OID_IFSPEED}.3": "100000000"}
    assert _get_port_speed(low, high, 3) == 1000


def test_get_port_speed_falls_back_to_ifspeed() -> None:
    """ifSpeed (bits/s) is converted to Mbps when ifHighSpeed is absent."""
    high: dict[str, str] = {}
    low = {f"{CONF_OID_IFSPEED}.3": "1000000000"}
    assert _get_port_speed(low, high, 3) == 1000


def test_get_port_speed_ifspeed_when_high_unparseable() -> None:
    """A non-numeric ifHighSpeed falls through to ifSpeed."""
    high = {f"{CONF_OID_IFHIGHSPEED}.3": "notanumber"}
    low = {f"{CONF_OID_IFSPEED}.3": "100000000"}
    assert _get_port_speed(low, high, 3) == 100


def test_get_port_speed_none_available() -> None:
    """With no speed data at all the result is 0."""
    assert _get_port_speed({}, {}, 3) == 0


# ── _generate_port_name ──────────────────────────────────────────────────────
def test_generate_port_name_slot_port() -> None:
    """slot:/port: descriptors yield 'Port <port-number>'."""
    assert _generate_port_name("Slot:1 Port:5", "slot:1 port:5", 9) == "Port 5"


def test_generate_port_name_pure_numeric() -> None:
    """A numeric descriptor becomes 'Port <n>'."""
    assert _generate_port_name("7", "7", 9) == "Port 7"


def test_generate_port_name_cisco_trailing_index() -> None:
    """Cisco GigabitEthernet-style names use the trailing index."""
    assert _generate_port_name(
        "GigabitHethernet1/0/24", "gigabithethernet1/0/24", 9
    ) == ("Port 24")


def test_generate_port_name_already_has_port_word() -> None:
    """A descriptor already containing 'port ' is returned untouched."""
    assert _generate_port_name("Port 3", "port 3", 9) == "Port 3"


def test_generate_port_name_standard_iface_kept() -> None:
    """Standard interface prefixes (eth/ge./swp/xe.) are kept verbatim."""
    assert _generate_port_name("eth0", "eth0", 9) == "eth0"


def test_generate_port_name_fallback_uses_logical_port() -> None:
    """An unrecognized descriptor falls back to the logical port number."""
    assert _generate_port_name("weirdname", "weirdname", 4) == "Port 4"


# ── _credentials ─────────────────────────────────────────────────────────────
def test_credentials_v1_for_model_zero() -> None:
    """mp_model 0 selects SNMP v1 credentials."""
    assert isinstance(_credentials(0, "public"), V1)


def test_credentials_v2c_for_model_one() -> None:
    """mp_model 1 selects SNMP v2c credentials."""
    assert isinstance(_credentials(1, "public"), V2C)


def test_credentials_v2c_for_other_models() -> None:
    """Any non-zero mp_model falls through to v2c."""
    assert isinstance(_credentials(2, "public"), V2C)
