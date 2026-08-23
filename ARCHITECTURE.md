# Architecture

Switch Port Card Pro is a SNMP-polling Home Assistant integration that exposes
per-port switch state as sensors, plus a Lovelace card that renders them. This
document covers the design points this fork adds or hardens; see the original
[partach/switch_port_card_pro](https://github.com/partach/switch_port_card_pro)
for the base card/SNMP behaviour.

## Polling

A `DataUpdateCoordinator` per configured switch polls a set of SNMP OIDs
(status, speed, PoE, rx/tx, names/VLANs — all configurable, with sane defaults
per manufacturer) and builds per-port state. Each port is a device with its own
diagnostic sensors.

## Port-to-device MAC linking

Opt-in per switch (`enable_port_mac_link`, default on). On each poll the
coordinator walks the bridge forwarding database (`dot1qTpFdbPort`) and maps
`ifIndex → learned unicast MAC(s)`. A port device is stamped with a
`(CONNECTION_NETWORK_MAC, mac)` connection only when:

- the port has exactly **one** learned client MAC, **and**
- that MAC is learned on exactly **one** port (dedup: a roaming client or stale
  FDB entry seen on two ports is skipped, so two port devices in the same config
  entry never claim the same MAC and collide).

In Home Assistant 2026.8+ a shared MAC connection **links** the port device to
whichever device carries that MAC — so a port links to its ESPHome/Konnected
panel, camera, UPS, etc. (pairs well with `ha-device-mac-link`, which stamps the
device side).

### Reconcile

The stamp is reconciled to the port's _current_ single client via
`async_update_device(new_connections=...)`: the new MAC is added and any
previously-stamped network MAC is pruned, so a port that saw a different client
before is not left linked to every host ever seen on it. Only network-MAC
connections are touched; cross-entry shared MACs link rather than raise.

## Signature guard

`tests/test_ha_signature_compat.py` asserts the shape of the HA APIs this
integration leans on (device-registry connection APIs, `DeviceInfo.connections`,
`DataUpdateCoordinator`, `Store`, sensor entity). The `ha-dev-compat` workflow
runs it against Home Assistant's `dev` branch weekly as an early-warning canary.
