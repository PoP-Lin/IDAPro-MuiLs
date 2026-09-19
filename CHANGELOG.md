# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0-beta.2] - 2026-09-20

### Added

- Read-only IDA UI/API inventory collector and a Windows 9.3/9.4 compatibility
  validation plan. IDA 9.4 GUI support remains pending runtime verification.

### Changed

- Publish 1.1.0-beta.2 as a prerelease; the stable 1.0.0 release remains available.
- Use IDA 9.4's optional `UI_Hooks.about_to_exit` event to restore Qt overlays
  and native hooks before UI destruction. Keep the 9.3 unload path and make
  cleanup idempotent when early shutdown is followed by plugin unloading.

## [1.0.0] - 2026-09-19

### Added

- Automatic IDAPython startup loader and persistent appearance settings.
- Modern dark styling for IDA 9.3 menus, toolbars, docks, dialogs, choosers,
  navigation band, scrollbars, graph views, and compatible plugin panels.
- Continuous rounded row selection for Functions, Names, and Strings.
- Scoped styling API for third-party Qt plugin panels.
- Smooth Windows resize handling and rounded native menu integration.
- Safe QObject identity handling while PySide6 6.8 destroys dynamic panels.
- Offline regression checks, reproducible release packaging, and GitHub CI.

[Unreleased]: https://github.com/PoP-Lin/IDAPro-MuiLs/compare/v1.1.0-beta.2...HEAD
[1.1.0-beta.2]: https://github.com/PoP-Lin/IDAPro-MuiLs/releases/tag/v1.1.0-beta.2
[1.0.0]: https://github.com/PoP-Lin/IDAPro-MuiLs/releases/tag/v1.0.0
