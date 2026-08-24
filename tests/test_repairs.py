# Copyright (c) 2025 partach (original switch_port_card_pro)
# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu> (modifications)
# SPDX-License-Identifier: MIT

"""Tests for :mod:`custom_components.switch_port_card_pro.repairs`.

Exercises the port-down :class:`RepairsFlow` end to end without any I/O:

* ``async_create_fix_flow`` returns a ``PortDownRepairFlow``,
* the initial step shows the four-option navigation menu,
* each action step awaits the matching ``PortEntityManager`` method with the
  right port and finishes the flow with a ``CREATE_ENTRY`` result, and
* the None-guards hold (missing manager, or missing port) so no manager
  method is awaited and the flow still finishes cleanly.

The manager is a plain :class:`~unittest.mock.AsyncMock`; it is reached via a
lightweight fake coordinator parked in ``hass.data`` exactly where
``_manager()`` looks for it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.switch_port_card_pro.const import DOMAIN
from custom_components.switch_port_card_pro.repairs import (
    PortDownRepairFlow,
    async_create_fix_flow,
)

ENTRY_ID = "entry-abc"
PORT = "12"


def _install_manager(hass: HomeAssistant, manager: Any) -> None:
    """Park a fake coordinator exposing ``entity_manager`` in ``hass.data``.

    Mirrors the layout ``PortDownRepairFlow._manager()`` reads:
    ``hass.data[DOMAIN][entry_id].entity_manager``.
    """
    coordinator = SimpleNamespace(entity_manager=manager)
    hass.data[DOMAIN] = {ENTRY_ID: coordinator}


def _make_flow(hass: HomeAssistant, data: dict[str, Any] | None) -> PortDownRepairFlow:
    return PortDownRepairFlow(hass, issue_id="port_down_12", data=data)


async def test_async_create_fix_flow_returns_repair_flow(
    hass: HomeAssistant,
) -> None:
    """The entrypoint builds a ``PortDownRepairFlow`` (a ``RepairsFlow``)."""
    flow = await async_create_fix_flow(
        hass, "port_down_12", {"entry_id": ENTRY_ID, "port": PORT}
    )
    assert isinstance(flow, PortDownRepairFlow)
    assert isinstance(flow, RepairsFlow)


async def test_init_step_shows_menu(hass: HomeAssistant) -> None:
    """The initial step is a menu offering the four remediation actions."""
    flow = _make_flow(hass, {"entry_id": ENTRY_ID, "port": PORT})
    result = await flow.async_step_init()

    assert result["type"] == FlowResultType.MENU
    assert result["step_id"] == "init"
    assert result["menu_options"] == [
        "disable_this",
        "disable_all",
        "ignore",
        "allow_flap",
    ]


async def test_disable_this_awaits_manager_with_port(
    hass: HomeAssistant,
) -> None:
    """``disable_this`` disables just this port, then finishes the flow."""
    manager = AsyncMock()
    _install_manager(hass, manager)
    flow = _make_flow(hass, {"entry_id": ENTRY_ID, "port": PORT})

    result = await flow.async_step_disable_this()

    manager.async_disable_port.assert_awaited_once_with(PORT)
    manager.async_disable_all_flagged.assert_not_awaited()
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_disable_all_awaits_flagged(hass: HomeAssistant) -> None:
    """``disable_all`` disables every flagged port, then finishes the flow."""
    manager = AsyncMock()
    _install_manager(hass, manager)
    flow = _make_flow(hass, {"entry_id": ENTRY_ID, "port": PORT})

    result = await flow.async_step_disable_all()

    manager.async_disable_all_flagged.assert_awaited_once_with()
    manager.async_disable_port.assert_not_awaited()
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_ignore_awaits_manager_with_port(hass: HomeAssistant) -> None:
    """``ignore`` ignores this port, then finishes the flow."""
    manager = AsyncMock()
    _install_manager(hass, manager)
    flow = _make_flow(hass, {"entry_id": ENTRY_ID, "port": PORT})

    result = await flow.async_step_ignore()

    manager.async_ignore_port.assert_awaited_once_with(PORT)
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_allow_flap_awaits_manager_with_port(
    hass: HomeAssistant,
) -> None:
    """``allow_flap`` mutes this port, then finishes the flow."""
    manager = AsyncMock()
    _install_manager(hass, manager)
    flow = _make_flow(hass, {"entry_id": ENTRY_ID, "port": PORT})

    result = await flow.async_step_allow_flap()

    manager.async_allow_flap.assert_awaited_once_with(PORT)
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_action_no_manager_still_creates_entry(
    hass: HomeAssistant,
) -> None:
    """With no coordinator in ``hass.data`` the action is a clean no-op.

    ``_manager()`` returns ``None`` (nothing to await); the flow still
    finishes with a ``CREATE_ENTRY`` result rather than raising.
    """
    flow = _make_flow(hass, {"entry_id": ENTRY_ID, "port": PORT})

    result = await flow.async_step_disable_this()

    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_port_actions_no_port_skip_manager(hass: HomeAssistant) -> None:
    """A manager present but no ``port`` in data skips port-scoped calls.

    ``disable_this`` / ``ignore`` / ``allow_flap`` are all guarded on the
    port; each must leave the manager untouched and still finish the flow.
    ``disable_all`` is port-independent and still runs.
    """
    manager = AsyncMock()
    _install_manager(hass, manager)
    flow = _make_flow(hass, {"entry_id": ENTRY_ID})

    for step in (
        flow.async_step_disable_this,
        flow.async_step_ignore,
        flow.async_step_allow_flap,
    ):
        result = await step()
        assert result["type"] == FlowResultType.CREATE_ENTRY

    manager.async_disable_port.assert_not_awaited()
    manager.async_ignore_port.assert_not_awaited()
    manager.async_allow_flap.assert_not_awaited()

    # Port-independent action is unaffected by the missing port.
    result = await flow.async_step_disable_all()
    manager.async_disable_all_flagged.assert_awaited_once_with()
    assert result["type"] == FlowResultType.CREATE_ENTRY
