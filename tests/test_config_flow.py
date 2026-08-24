# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# SPDX-License-Identifier: MIT

"""Tests for the Switch Port Card Pro config and options flows."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.switch_port_card_pro.const import (
    CONF_COMMUNITY,
    CONF_HOST,
    CONF_SNMP_PORT,
    DOMAIN,
)

_SNMP_GET = "custom_components.switch_port_card_pro.config_flow.async_snmp_get"

_USER_INPUT: dict[str, Any] = {
    CONF_HOST: "192.168.1.10",
    CONF_COMMUNITY: "public",
    CONF_SNMP_PORT: 161,
}


@pytest.fixture(autouse=True)
def bypass_integration_deps() -> Generator[None]:
    """Skip loading manifest deps (lovelace/frontend -> http) during flow init.

    Setting up ``http`` would open a socket, which the test harness blocks. The
    config/options flows under test do not need those dependencies to run.
    """
    with (
        patch(
            "homeassistant.config_entries.async_process_deps_reqs",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "homeassistant.setup.async_process_deps_reqs",
            new=AsyncMock(return_value=None),
        ),
    ):
        yield


async def test_user_flow_happy_path(hass: HomeAssistant) -> None:
    """A reachable switch creates a config entry with the expected data."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    # The SNMP probe must succeed; async_setup_entry is stubbed so the freshly
    # created entry does not spin up a real coordinator or touch the network.
    with (
        patch(_SNMP_GET, new=AsyncMock(return_value="switch-sysname")),
        patch(
            "custom_components.switch_port_card_pro.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(_USER_INPUT)
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "192.168.1.10"
    assert result["data"] == {
        CONF_HOST: "192.168.1.10",
        CONF_COMMUNITY: "public",
        CONF_SNMP_PORT: 161,
    }
    # Initial options are seeded on entry creation.
    assert result["options"]["snmp_version"] == "v2c"
    assert result["options"]["include_vlans"] is True


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """An unreachable switch (SNMP returns None) surfaces a cannot_connect error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with patch(_SNMP_GET, new=AsyncMock(return_value=None)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(_USER_INPUT)
        )

    # Re-shows the form with the error rather than creating an entry.
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_duplicate_host_aborts(hass: HomeAssistant) -> None:
    """A host already configured aborts via _abort_if_unique_id_configured."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="192.168.1.10",
        data={
            CONF_HOST: "192.168.1.10",
            CONF_COMMUNITY: "public",
            CONF_SNMP_PORT: 161,
        },
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    # SNMP must never be reached: the abort happens before the connection test.
    with patch(_SNMP_GET, new=AsyncMock(return_value="switch-sysname")) as snmp:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(_USER_INPUT)
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    snmp.assert_not_called()


async def test_options_flow_opens_and_saves(hass: HomeAssistant) -> None:
    """The options flow opens, then saves merged options on submit."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="192.168.1.10",
        data={
            CONF_HOST: "192.168.1.10",
            CONF_COMMUNITY: "public",
            CONF_SNMP_PORT: 161,
        },
        options={"snmp_version": "v2c", "update_interval": 20},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "options"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"update_interval": 45}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["update_interval"] == 45
    # Existing option keys are preserved through the merge.
    assert result["data"]["snmp_version"] == "v2c"
    assert entry.options["update_interval"] == 45


async def test_options_flow_rejects_invalid_oid(hass: HomeAssistant) -> None:
    """A non-numeric OID is rejected with an invalid_oid error, no entry saved."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="192.168.1.11",
        data={
            CONF_HOST: "192.168.1.11",
            CONF_COMMUNITY: "public",
            CONF_SNMP_PORT: 161,
        },
        options={"snmp_version": "v2c", "update_interval": 20},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"oid_rx": "not-an-oid"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "options"
    assert result["errors"] == {"oid_rx": "invalid_oid"}
