# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# SPDX-License-Identifier: MIT

"""Tests for registering the card as a Lovelace resource."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.switch_port_card_pro import async_register_card

CARD_PATH = "switch_port_card_pro_card/switch-port-card-pro.js"


def _hass_with_resources(urls: list[str]) -> tuple[MagicMock, AsyncMock]:
    create_item = AsyncMock()
    resources = SimpleNamespace(
        loaded=True,
        async_items=lambda: [{"url": url} for url in urls],
        async_create_item=create_item,
    )
    hass = MagicMock()
    hass.data = {"lovelace": SimpleNamespace(resources=resources)}
    return hass, create_item


@pytest.mark.parametrize(
    "existing",
    [
        f"/hacsfiles/{CARD_PATH}",
        f"/hacsfiles/{CARD_PATH}?hacstag=123",
        f"/local/community/{CARD_PATH}",
        f"/local/community/{CARD_PATH}?v=123",
    ],
)
async def test_existing_resource_is_not_duplicated(existing: str) -> None:
    """A registered card is kept under the HACS or the Marketplace URL."""
    hass, create_item = _hass_with_resources(["/local/other.js", existing])

    await async_register_card(hass, MagicMock())

    create_item.assert_not_awaited()


async def test_missing_resource_is_created() -> None:
    """The card is registered when no resource points at it."""
    hass, create_item = _hass_with_resources(
        [f"/local/community/other_card/{CARD_PATH.rsplit('/', 1)[1]}"]
    )

    await async_register_card(hass, MagicMock())

    create_item.assert_awaited_once_with(
        {"res_type": "module", "url": f"/hacsfiles/{CARD_PATH}"}
    )
