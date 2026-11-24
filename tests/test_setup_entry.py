# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# SPDX-License-Identifier: MIT

"""Tests for async_setup_entry's handling of an unreachable switch."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.switch_port_card_pro import (
    REACHABILITY_RETRIES,
    REACHABILITY_TIMEOUT_S,
)
from custom_components.switch_port_card_pro.const import (
    CONF_COMMUNITY,
    CONF_HOST,
    CONF_OID_SYSNAME,
    CONF_SNMP_PORT,
    DOMAIN,
)

_MODULE = "custom_components.switch_port_card_pro"


@pytest.fixture(autouse=True)
def bypass_setup_side_effects() -> Generator[None]:
    """Skip manifest deps and the card install, which need http and lovelace."""
    with (
        patch(
            "homeassistant.config_entries.async_process_deps_reqs",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "homeassistant.setup.async_process_deps_reqs",
            new=AsyncMock(return_value=None),
        ),
        patch(f"{_MODULE}.async_install_frontend_resource", new=AsyncMock()),
        patch(f"{_MODULE}.async_register_card", new=AsyncMock()),
    ):
        yield


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="switch.example",
        data={CONF_HOST: "192.0.2.10", CONF_COMMUNITY: "public"},
        options={CONF_SNMP_PORT: 161},
    )
    entry.add_to_hass(hass)
    return entry


async def test_unreachable_switch_retries_setup(hass: HomeAssistant) -> None:
    """No SNMP answer: setup is retried, and discovery and platforms never run."""
    entry = _entry(hass)
    with (
        patch(f"{_MODULE}.async_snmp_get", new=AsyncMock(return_value=None)) as probe,
        patch(f"{_MODULE}.discover_physical_ports", new=AsyncMock()) as discover,
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ) as forward,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    probe.assert_awaited_once()
    args, kwargs = probe.call_args
    assert args[1:5] == ("192.0.2.10", "public", 161, CONF_OID_SYSNAME)
    assert kwargs["timeout"] == REACHABILITY_TIMEOUT_S
    assert kwargs["retries"] == REACHABILITY_RETRIES
    discover.assert_not_awaited()
    forward.assert_not_awaited()


async def test_reachable_switch_proceeds_to_discovery(hass: HomeAssistant) -> None:
    """An SNMP answer lets setup carry on to port discovery."""
    entry = _entry(hass)
    with (
        patch(f"{_MODULE}.async_snmp_get", new=AsyncMock(return_value="switch")),
        patch(
            f"{_MODULE}.discover_physical_ports",
            new=AsyncMock(side_effect=RuntimeError("reached discovery")),
        ) as discover,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    discover.assert_awaited_once()
    # Not SETUP_RETRY: the probe passed, and the forced discovery error is a
    # plain failure rather than "not ready".
    assert entry.state is ConfigEntryState.SETUP_ERROR
