# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# SPDX-License-Identifier: MIT

"""Tests for :mod:`custom_components.switch_port_card_pro.entity_manager`.

Covers the tractable, high-value logic of ``PortEntityManager``:

* the pure flap/liveness helpers (``_note_transition``, ``_is_flapping``,
  ``_poe_active``),
* ``Store`` persistence (save→load round-trip, and the defaults merge that
  lets an older store gain newly-added keys),
* the Repair-flow actions (disable / ignore / allow-flap / flagged-ports), and
* the reconcile state machine (raise on long-down, suppress while flapping,
  auto re-enable after a clean on-streak, clear issues when disabled).

No real network I/O happens: the coordinator is a lightweight fake exposing
only the attributes the code under test reads.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.switch_port_card_pro import entity_manager as em
from custom_components.switch_port_card_pro.const import (
    CONF_AUTO_MANAGE_ENTITIES,
    CONF_DOWN_GRACE_HOURS,
    CONF_UP_RESTORE_CYCLES,
    DOMAIN,
)
from custom_components.switch_port_card_pro.entity_manager import (
    FLAP_MIN_TRANSITIONS,
    PortEntityManager,
)

# --- helpers ---------------------------------------------------------------


def _make_coordinator(
    ports: list[int],
    data_ports: dict[str, dict[str, Any]],
    host: str = "switch.local",
) -> Any:
    """A stand-in coordinator exposing only what the manager reads."""
    return SimpleNamespace(
        ports=ports,
        host=host,
        data=SimpleNamespace(ports=data_ports),
    )


def _make_entry(**options: Any) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, data={"host": "switch.local"}, options=options
    )


def _register_port_entity(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    port: int,
    key: str,
    *,
    disabled_by: er.RegistryEntryDisabler | None = None,
) -> er.RegistryEntry:
    """Register a per-port entity matching the manager's unique_id grammar."""
    reg = er.async_get(hass)
    return reg.async_get_or_create(
        domain="sensor",
        platform=DOMAIN,
        unique_id=f"abc_port_{port}_{key}",
        config_entry=entry,
        disabled_by=disabled_by,
    )


def _disabled_by(
    hass: HomeAssistant, entity_id: str
) -> er.RegistryEntryDisabler | None:
    """Fetch an entry's ``disabled_by``, asserting the entry still exists."""
    ent = er.async_get(hass).async_get(entity_id)
    assert ent is not None
    return ent.disabled_by


# --- pure helper: _note_transition ----------------------------------------


def test_note_transition_first_observation_sets_status_without_a_change() -> None:
    """The first poll seeds ``last_status`` but records no transition."""
    st = em._default_port_state()
    changed = PortEntityManager._note_transition(st, True, now=100.0, grace_s=3600.0)
    assert changed is True
    assert st["last_status"] == "on"
    assert st["transitions"] == []


def test_note_transition_records_up_down_change() -> None:
    """A real up→down flip appends the timestamp and flips last_status."""
    st = em._default_port_state()
    st["last_status"] = "on"
    changed = PortEntityManager._note_transition(st, False, now=200.0, grace_s=3600.0)
    assert changed is True
    assert st["last_status"] == "off"
    assert st["transitions"] == [200.0]


def test_note_transition_no_change_when_status_stable() -> None:
    """Same status two polls running: nothing recorded, not dirtied."""
    st = em._default_port_state()
    st["last_status"] = "on"
    changed = PortEntityManager._note_transition(st, True, now=300.0, grace_s=3600.0)
    assert changed is False
    assert st["transitions"] == []


def test_note_transition_prunes_transitions_outside_half_grace_window() -> None:
    """Old transitions beyond grace/2 are dropped even on a stable poll."""
    now = 10_000.0
    grace_s = 3600.0  # window = 1800s
    st = em._default_port_state()
    st["last_status"] = "on"
    st["transitions"] = [now - 5000.0, now - 100.0]  # first is stale, second fresh
    changed = PortEntityManager._note_transition(st, True, now=now, grace_s=grace_s)
    assert changed is True
    assert st["transitions"] == [now - 100.0]


def test_note_transition_unknown_status_is_a_noop() -> None:
    """``status_on=None`` means no usable data: neither recorded nor lost."""
    st = em._default_port_state()
    st["last_status"] = "off"
    st["transitions"] = [1.0]
    changed = PortEntityManager._note_transition(st, None, now=500.0, grace_s=3600.0)
    assert changed is False
    assert st["last_status"] == "off"
    assert st["transitions"] == [1.0]


# --- pure helper: _is_flapping --------------------------------------------


def test_is_flapping_true_at_threshold_within_window() -> None:
    now = 1000.0
    grace_s = 3600.0  # window = 1800
    st = em._default_port_state()
    st["transitions"] = [now - 10.0] * FLAP_MIN_TRANSITIONS
    assert PortEntityManager._is_flapping(st, now, grace_s) is True


def test_is_flapping_false_below_threshold() -> None:
    now = 1000.0
    st = em._default_port_state()
    st["transitions"] = [now - 10.0] * (FLAP_MIN_TRANSITIONS - 1)
    assert PortEntityManager._is_flapping(st, now, 3600.0) is False


def test_is_flapping_ignores_transitions_outside_window() -> None:
    """Transitions older than grace/2 do not count toward flapping."""
    now = 100_000.0
    grace_s = 3600.0  # window = 1800
    st = em._default_port_state()
    st["transitions"] = [now - 5000.0] * FLAP_MIN_TRANSITIONS  # all stale
    assert PortEntityManager._is_flapping(st, now, grace_s) is False


# --- pure helper: _poe_active ---------------------------------------------


def test_poe_active_delivering_power_status() -> None:
    assert PortEntityManager._poe_active({"poe_status": 3}) is True


def test_poe_active_positive_measured_power() -> None:
    assert PortEntityManager._poe_active({"poe_power": 4.2}) is True


def test_poe_active_false_when_idle_or_unparseable() -> None:
    assert PortEntityManager._poe_active({}) is False
    assert PortEntityManager._poe_active({"poe_power": 0}) is False
    assert PortEntityManager._poe_active({"poe_power": None}) is False
    assert PortEntityManager._poe_active({"poe_power": "nonsense"}) is False


# --- persistence via Store -------------------------------------------------


async def test_store_round_trip(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """State saved by one manager loads intact in a fresh manager."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator([1], {"1": {}})

    m1 = PortEntityManager(hass, entry, coordinator)
    m1._state["1"] = em._default_port_state()
    m1._state["1"]["disabled_uids"] = ["abc_port_1_rx_rate"]
    m1._state["1"]["ignored"] = True
    m1._state["1"]["transitions"] = [111.0, 222.0]
    await m1._async_save()

    m2 = PortEntityManager(hass, entry, coordinator)
    await m2.async_load()

    assert m2._state["1"]["disabled_uids"] == ["abc_port_1_rx_rate"]
    assert m2._state["1"]["ignored"] is True
    assert m2._state["1"]["transitions"] == [111.0, 222.0]


async def test_async_load_merges_defaults_onto_old_store(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A store written before newer keys existed gains them on load."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    key = f"{DOMAIN}.{entry.entry_id}.entity_manager"
    # Only the two oldest keys are present in this simulated legacy store.
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {"ports": {"3": {"down_since": 123.0, "ignored": True}}},
    }
    coordinator = _make_coordinator([3], {"3": {}})
    manager = PortEntityManager(hass, entry, coordinator)
    await manager.async_load()

    st = manager._state["3"]
    assert st["down_since"] == 123.0  # preserved
    assert st["ignored"] is True  # preserved
    # Newly-added keys back-filled from defaults:
    assert st["flap_muted"] is False
    assert st["transitions"] == []
    assert st["disabled_uids"] == []
    assert st["issue_open"] is False


# --- Repair-flow actions ---------------------------------------------------


async def test_disable_port_disables_only_managed_entities(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """``async_disable_port`` disables per-port extras but never the anchors."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    rx = _register_port_entity(hass, entry, 5, "rx_rate")
    tx = _register_port_entity(hass, entry, 5, "tx_rate")
    status = _register_port_entity(hass, entry, 5, "status")  # unmanaged anchor
    coordinator = _make_coordinator([5], {"5": {"status": "off"}})
    manager = PortEntityManager(hass, entry, coordinator)

    n = await manager.async_disable_port("5")

    assert n == 2
    assert _disabled_by(hass, rx.entity_id) == er.RegistryEntryDisabler.INTEGRATION
    assert _disabled_by(hass, tx.entity_id) == er.RegistryEntryDisabler.INTEGRATION
    assert _disabled_by(hass, status.entity_id) is None  # anchor untouched
    assert manager._state["5"]["disabled_uids"] == sorted(
        {"abc_port_5_rx_rate", "abc_port_5_tx_rate"}
    )
    assert manager._state["5"]["down_since"] is None


async def test_disable_port_clears_open_issue(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Disabling a flagged port retracts its Repair issue."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator([9], {"9": {"status": "off"}})
    manager = PortEntityManager(hass, entry, coordinator)
    issue_id = em._issue_id(entry.entry_id, "9")
    manager._raise_issue("9")
    manager._state["9"] = em._default_port_state()
    manager._state["9"]["issue_open"] = True

    await manager.async_disable_port("9")

    assert manager._state["9"]["issue_open"] is False
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_ignore_port_sets_flag_and_clears_issue(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator([4], {"4": {"status": "off"}})
    manager = PortEntityManager(hass, entry, coordinator)
    issue_id = em._issue_id(entry.entry_id, "4")
    manager._raise_issue("4")
    manager._state["4"] = em._default_port_state()
    manager._state["4"]["issue_open"] = True

    await manager.async_ignore_port(4)

    st = manager._state["4"]
    assert st["ignored"] is True
    assert st["flap_muted"] is False
    assert st["issue_open"] is False
    assert st["down_since"] is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_allow_flap_mutes_without_ignoring(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator([6], {"6": {"status": "off"}})
    manager = PortEntityManager(hass, entry, coordinator)

    await manager.async_allow_flap("6")

    st = manager._state["6"]
    assert st["flap_muted"] is True
    assert st["ignored"] is False  # distinct from ignore
    assert st["down_since"] is None


async def test_flagged_ports_and_disable_all_flagged(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """``flagged_ports`` lists open issues (sorted ints); disable-all sweeps them."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    _register_port_entity(hass, entry, 2, "rx_rate")
    _register_port_entity(hass, entry, 10, "rx_rate")
    coordinator = _make_coordinator([2, 10], {"2": {}, "10": {}})
    manager = PortEntityManager(hass, entry, coordinator)
    for port in ("10", "2"):
        manager._state[port] = em._default_port_state()
        manager._state[port]["issue_open"] = True

    assert manager.flagged_ports() == [2, 10]  # numeric sort, not lexical

    total = await manager.async_disable_all_flagged()

    assert total == 2  # one managed extra disabled per flagged port
    reg = er.async_get(hass)
    disabled = [
        e.unique_id
        for e in er.async_entries_for_config_entry(reg, entry.entry_id)
        if e.disabled_by == er.RegistryEntryDisabler.INTEGRATION
    ]
    assert sorted(disabled) == ["abc_port_10_rx_rate", "abc_port_2_rx_rate"]


# --- reconcile state machine ----------------------------------------------


async def test_reconcile_raises_issue_when_down_past_grace(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A long-down port with live extras raises a Repair issue."""
    entry = _make_entry(
        **{
            CONF_AUTO_MANAGE_ENTITIES: True,
            CONF_DOWN_GRACE_HOURS: 1,  # grace = 3600s
        }
    )
    entry.add_to_hass(hass)
    _register_port_entity(hass, entry, 5, "rx_rate")
    coordinator = _make_coordinator(
        [5], {"5": {"status": "off", "last_change_seconds": 100_000}}
    )
    manager = PortEntityManager(hass, entry, coordinator)

    await manager._async_reconcile()

    assert manager._state["5"]["issue_open"] is True
    assert manager.flagged_ports() == [5]
    issue_id = em._issue_id(entry.entry_id, "5")
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None


async def test_reconcile_flapping_port_is_not_flagged(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A down-but-flapping port is treated as unstable, never nagged."""
    entry = _make_entry(
        **{
            CONF_AUTO_MANAGE_ENTITIES: True,
            CONF_DOWN_GRACE_HOURS: 1,  # grace = 3600s, window = 1800s
        }
    )
    entry.add_to_hass(hass)
    _register_port_entity(hass, entry, 8, "rx_rate")
    now = time.time()
    coordinator = _make_coordinator([8], {"8": {"status": "off"}})
    manager = PortEntityManager(hass, entry, coordinator)
    st = em._default_port_state()
    st["last_status"] = "off"
    st["down_since"] = now - 100_000  # well past grace on its own
    st["transitions"] = [now - 10.0] * FLAP_MIN_TRANSITIONS  # recent → flapping
    manager._state["8"] = st

    await manager._async_reconcile()

    assert manager._state["8"]["issue_open"] is False
    issue_id = em._issue_id(entry.entry_id, "8")
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_reconcile_reenables_after_up_streak(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A port we disabled, seen up for ``up_restore_cycles`` polls, is restored."""
    entry = _make_entry(
        **{
            CONF_AUTO_MANAGE_ENTITIES: True,
            CONF_UP_RESTORE_CYCLES: 2,
        }
    )
    entry.add_to_hass(hass)
    ent = _register_port_entity(
        hass, entry, 7, "rx_rate", disabled_by=er.RegistryEntryDisabler.INTEGRATION
    )
    coordinator = _make_coordinator([7], {"7": {"status": "on"}})
    manager = PortEntityManager(hass, entry, coordinator)
    st = em._default_port_state()
    st["disabled_uids"] = ["abc_port_7_rx_rate"]
    manager._state["7"] = st

    # First up poll: streak = 1, still below threshold — stays disabled.
    await manager._async_reconcile()
    assert manager._on_streak["7"] == 1
    assert _disabled_by(hass, ent.entity_id) is not None
    assert manager._state["7"]["disabled_uids"] == ["abc_port_7_rx_rate"]

    # Second up poll: streak reaches 2 — restore exactly our disabled set.
    await manager._async_reconcile()
    assert _disabled_by(hass, ent.entity_id) is None
    assert manager._state["7"]["disabled_uids"] == []
    assert manager._on_streak["7"] == 0


async def test_reconcile_up_clears_ignore_and_issue(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """An ignored/flagged port coming back up re-arms and retracts its issue."""
    entry = _make_entry(**{CONF_AUTO_MANAGE_ENTITIES: True})
    entry.add_to_hass(hass)
    coordinator = _make_coordinator([3], {"3": {"status": "on"}})
    manager = PortEntityManager(hass, entry, coordinator)
    manager._raise_issue("3")
    st = em._default_port_state()
    st["ignored"] = True
    st["issue_open"] = True
    st["down_since"] = time.time() - 50.0
    manager._state["3"] = st

    await manager._async_reconcile()

    assert manager._state["3"]["ignored"] is False
    assert manager._state["3"]["issue_open"] is False
    assert manager._state["3"]["down_since"] is None
    issue_id = em._issue_id(entry.entry_id, "3")
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_reconcile_clears_issues_when_feature_disabled(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """With auto-manage off, any lingering issues we raised are cleared."""
    entry = _make_entry(**{CONF_AUTO_MANAGE_ENTITIES: False})
    entry.add_to_hass(hass)
    coordinator = _make_coordinator([1], {"1": {"status": "off"}})
    manager = PortEntityManager(hass, entry, coordinator)
    manager._raise_issue("1")
    manager._state["1"] = em._default_port_state()
    manager._state["1"]["issue_open"] = True

    await manager._async_reconcile()

    assert manager._state["1"]["issue_open"] is False
    issue_id = em._issue_id(entry.entry_id, "1")
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
