# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# SPDX-License-Identifier: MIT
"""Pre-alias httpx2 before pytest.main so HA dev's `__init__` doesn't crash
on pytest-homeassistant-custom-component's earlier httpx import."""

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

    return pytest.main(["tests/test_ha_signature_compat.py", "-v"])


if __name__ == "__main__":
    sys.exit(main())
