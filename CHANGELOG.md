# Changelog

## [1.1.1](https://github.com/bakerkj/ha-switch-port-card-pro/compare/v1.1.0...v1.1.1) (2026-09-04)


### Miscellaneous Chores

* **deps:** update anthropics/claude-code-action action to v1.0.205 ([#16](https://github.com/bakerkj/ha-switch-port-card-pro/issues/16)) ([fe20718](https://github.com/bakerkj/ha-switch-port-card-pro/commit/fe207189c10c0c8c9f0a7dc7cec997f410d61a51))
* **deps:** update anthropics/claude-code-action action to v1.0.211 ([#20](https://github.com/bakerkj/ha-switch-port-card-pro/issues/20)) ([8a44365](https://github.com/bakerkj/ha-switch-port-card-pro/commit/8a4436500f8d4d6238d2385127af13636a738def))
* **deps:** update anthropics/claude-code-action action to v1.0.212 ([#21](https://github.com/bakerkj/ha-switch-port-card-pro/issues/21)) ([501fe68](https://github.com/bakerkj/ha-switch-port-card-pro/commit/501fe68429f26a2e7b77937903d15a51c54a86bb))
* **deps:** update dependency uv to v0.12.6 ([#14](https://github.com/bakerkj/ha-switch-port-card-pro/issues/14)) ([6993d04](https://github.com/bakerkj/ha-switch-port-card-pro/commit/6993d04fb0a4e06f8e2e303c5ea6f8b1725f87f9))
* **deps:** update dependency uv to v0.12.7 ([#17](https://github.com/bakerkj/ha-switch-port-card-pro/issues/17)) ([8e3d75b](https://github.com/bakerkj/ha-switch-port-card-pro/commit/8e3d75bfb881973e778913da7c197bb7df1afdd8))
* **deps:** update dependency uv to v0.12.8 ([#19](https://github.com/bakerkj/ha-switch-port-card-pro/issues/19)) ([e9128d0](https://github.com/bakerkj/ha-switch-port-card-pro/commit/e9128d0131261fde24fd24989450d7c032f7947a))
* **deps:** update pre-commit hook astral-sh/ruff-pre-commit to v0.16.5 ([#18](https://github.com/bakerkj/ha-switch-port-card-pro/issues/18)) ([3860849](https://github.com/bakerkj/ha-switch-port-card-pro/commit/38608494ec9d80efcea6ba0dfc95e8a649d63210))

## [1.1.0](https://github.com/bakerkj/ha-switch-port-card-pro/compare/v1.0.18...v1.1.0) (2026-08-24)


### Features

* link ports to their LLDP neighbour (AP/switch), FDB as fallback ([#12](https://github.com/bakerkj/ha-switch-port-card-pro/issues/12)) ([252b018](https://github.com/bakerkj/ha-switch-port-card-pro/commit/252b0188816b3a8ecf4a4114e45637416e68ad06))

## [1.0.18](https://github.com/bakerkj/ha-switch-port-card-pro/compare/v1.0.17...v1.0.18) (2026-08-24)


### Miscellaneous Chores

* set bakerkj as codeowner and point links at this repo ([#10](https://github.com/bakerkj/ha-switch-port-card-pro/issues/10)) ([4c8de8e](https://github.com/bakerkj/ha-switch-port-card-pro/commit/4c8de8eff1342b0fe004a0e09145c838c112d0e5))

## [1.0.17](https://github.com/bakerkj/ha-switch-port-card-pro/compare/v1.0.16...v1.0.17) (2026-08-24)


### Features

* adopt switch_port_card_pro as a robust HA integration ([d000785](https://github.com/bakerkj/ha-switch-port-card-pro/commit/d0007853fb8d79e3626999ed4656a35b312b3955))


### Bug Fixes

* import DeviceInfo from its canonical module in the signature guard ([25f2c29](https://github.com/bakerkj/ha-switch-port-card-pro/commit/25f2c29adb65fe213a82dcf0044513744b58cf86))


### Miscellaneous Chores

* add brand icon (svg + png) ([af563a2](https://github.com/bakerkj/ha-switch-port-card-pro/commit/af563a2498ac5a3d2b990bb98f87c703f79f8320))
* add brand icon (svg + png) ([9689620](https://github.com/bakerkj/ha-switch-port-card-pro/commit/968962075b9073f498c681b7c1888ed2c1e55fbc))
* drop unmaintained de/nl translations ([#8](https://github.com/bakerkj/ha-switch-port-card-pro/issues/8)) ([9c8a088](https://github.com/bakerkj/ha-switch-port-card-pro/commit/9c8a08870292448431d2b52d31de73905ad96c03))
* drop unreferenced fork screenshot assets ([#7](https://github.com/bakerkj/ha-switch-port-card-pro/issues/7)) ([7c8b9c9](https://github.com/bakerkj/ha-switch-port-card-pro/commit/7c8b9c9a328185ad391ae4eddc0dbae1c18a5162))
* make .copyright-header.txt the default (our own) header ([#9](https://github.com/bakerkj/ha-switch-port-card-pro/issues/9)) ([dc84801](https://github.com/bakerkj/ha-switch-port-card-pro/commit/dc84801b17fd2c8da6d07ed6dc09569179e684af))


### Code Refactoring

* drop bootstrap relaxations (ruff + mypy strict) ([2e45993](https://github.com/bakerkj/ha-switch-port-card-pro/commit/2e45993e2d39e530b8e410e64947046c7dea1e9a))
* narrow broad excepts to real types; drop ruff relaxations ([7cb3440](https://github.com/bakerkj/ha-switch-port-card-pro/commit/7cb3440ffcad298153063bb53122246057c0e11b))
* type the integration to mypy --strict; drop mypy relaxation ([277c045](https://github.com/bakerkj/ha-switch-port-card-pro/commit/277c045c533cf27826f1692c3c20d6a38e27a6c5))


### Tests

* add unit + reconcile test suite and enforce coverage floor ([#6](https://github.com/bakerkj/ha-switch-port-card-pro/issues/6)) ([3250519](https://github.com/bakerkj/ha-switch-port-card-pro/commit/32505193b6ad9725dc1de49ab1daa3b82028fa1b))

## Changelog
