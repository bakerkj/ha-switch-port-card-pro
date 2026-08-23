# Switch Port Card Pro (ha-switch-port-card-pro)

A Home Assistant integration **and** Lovelace card for per-port switch
monitoring over SNMP — link status, speed, PoE, traffic — with **optional
port-to-device MAC linking**: each single-client edge port is stamped with the
MAC it has learned (from the switch FDB), so in Home Assistant 2026.8+ the port
device links to whatever device carries that MAC (an ESPHome/Konnected panel, a
camera, a UPS, etc.).

> **Fork.** This is a hardened, independently-maintained fork of
> [partach/switch_port_card_pro](https://github.com/partach/switch_port_card_pro)
> (MIT, © 2025 partach). The HA domain is unchanged (`switch_port_card_pro`).
> See that project for the original card/SNMP documentation and screenshots.

## What's different here

- Port-to-device **MAC linking** via the switch FDB (`dot1qTpFdbPort`), opt-in
  per switch (default on), with dedup (a MAC learned on two ports is skipped)
  and reconcile (a port's stamped MAC is pruned/updated as its single client
  changes).
- Full integration tooling: uv, ruff/black/prettier/codespell via prek,
  commitlint, hassfest, HACS validation, mypy, release-please, Renovate, and a
  weekly Home-Assistant-`dev` API signature guard.

## Requirements

- Home Assistant **2026.8+** (the per-config-entry device split, where a shared
  MAC connection links two device entries).

## Installation (HACS)

1. Add `https://github.com/bakerkj/ha-switch-port-card-pro` as a custom
   repository (category: Integration).
2. Install **Switch Port Card Pro** and restart Home Assistant.
3. Add a switch via **Settings → Devices & Services → Add Integration**.

## Development

Uses [uv](https://docs.astral.sh/uv/) and Conventional Commits.

```bash
uvx prek install --overwrite --hook-type pre-commit --hook-type commit-msg
uv run pytest tests/
```

## License

MIT — see [LICENSE](LICENSE). Original work © 2025 partach; modifications © 2026
Kenneth Baker.
