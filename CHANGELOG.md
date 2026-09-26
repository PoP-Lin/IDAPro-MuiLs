# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- macOS support for IDA 9.4 (PySide6 6.8 / Qt 6.8, bundled Python 3.14) with
  platform font defaults (`Helvetica Neue`, `SF Mono`, `Menlo` fallbacks).
- `Modern OLED` theme: a true-black variant derived from `Modern Dark` at
  apply time; all Python paint runtimes share the derived palette.
- `muils.py`, a stdlib-only manager (`install`, `uninstall
  [--restore-backup]`, `status`, `enable`, `disable`, `theme`) that targets the
  per-user IDA plugin directory on Windows, macOS, and Linux with timestamped
  backups.
- `apply_panel_layout` setting; the balanced desktop layout and built-in
  column sizing are opt-in outside Windows.
- `verbose_log` setting; runtime diagnostics are no longer printed by default.

### Fixed

- IDA 9.4/macOS aborted (`recursive_mutex lock failed`) or segfaulted at exit
  when PySide-owned overlays, event filters, or `QTimer.singleShot` callbacks
  outlived interpreter finalisation. `term()` now restores, flushes deferred
  deletes, and cancels owned timers.
- Disabling the theme restores the byte-identical native stylesheet.
- The loader no longer raises during IDA startup when the package cannot be
  imported; it registers a skipped plugin and logs to `modern_ui/startup.log`.

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

[Unreleased]: https://github.com/PoP-Lin/IDAPro-MuiLs/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/PoP-Lin/IDAPro-MuiLs/releases/tag/v1.0.0
