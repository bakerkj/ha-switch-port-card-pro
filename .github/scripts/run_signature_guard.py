# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# SPDX-License-Identifier: MIT
"""Run the HA signature-compat tests against HA dev.

Pre-aliases httpx2 before pytest.main so HA dev's `__init__` doesn't crash on
an earlier real-httpx import, and skips pytest-homeassistant-custom-component,
which is built against released HA and imports private helpers dev removes."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import httpx2  # type: ignore[import-not-found,unused-ignore]
    except ImportError:
        pass
    else:
        httpx2.alias_httpx()

    import pytest

    # No HA test plugin and no conftest.py (its fixtures need the plugin): the
    # plugin is built for released HA and imports private helpers dev removes.
    # These tests take no fixtures, so neither is needed.
    return pytest.main(
        [
            "-p",
            "no:homeassistant",
            "--noconftest",
            "tests/test_ha_signature_compat.py",
            "-v",
        ]
    )


if __name__ == "__main__":
    sys.exit(main())
