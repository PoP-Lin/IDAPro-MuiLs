# IDAPro-MuiLs on macOS (IDA 9.4)

This branch ports the theme to IDA Pro 9.4 on macOS (tested on Apple Silicon,
IDA 9.4.260915, bundled Python 3.14, PySide6 6.8 / Qt 6.8). Windows-only
integrations (DWM dark title bars, WinEvent resize pausing, rounded popup
corners via DWM) are no-ops here; everything else works unchanged.

## What is different from the Windows release

- **Fonts**: defaults are `Helvetica Neue` (interface) and `SF Mono` (code)
  with macOS fallbacks (`.AppleSystemUIFont`, `Menlo`, `JetBrainsMono Nerd
  Font Mono`). Font size defaults to 11 pt.
- **Modern OLED theme**: a second theme derived from Modern Dark where every
  dark surface is pushed to true black (`#000000`) for OLED panels. Mid-tones,
  text and accent colours keep their hue. It is the default on macOS; switch
  back to Modern Dark in the settings dialog if preferred.
- **Desktop layout is opt-in**: the "balanced panel layout" and built-in
  column sizing rewrite IDA's saved desktop. They are off by default on macOS
  so enabling the theme changes pixels only. Turn them on in settings if
  wanted.
- **Clean shutdown**: IDA 9.4/macOS aborted or segfaulted at exit when
  PySide-owned overlays, event filters or pending timers were still alive
  during interpreter finalisation. The plugin now tears everything down
  synchronously in `term()` and cancels its own timers.
- **Exact restore**: disabling the theme returns `QApplication.styleSheet()`
  to the byte-identical string IDA had before, not a whitespace-trimmed copy.

- **Quiet startup**: the runtime diagnostics lines are off by default; set
  `"verbose_log": true` in `~/.idapro/modern_ui/config.json` to see them.
  The `PySide has not been widely tested on Python >= 3.14` line is printed
  by IDA itself about its bundled Python and is unrelated to the theme.

## Install (does not touch the IDA .app bundle)

```bash
./scripts/macos/install.sh
```

Copies the loader and package into `~/.idapro/plugins/` and records a
timestamped backup in `~/.idapro/muils-backup-<stamp>/` (previous plugin
files, previous `modern_ui/` settings, and `ida.reg`).

In IDA: `Ctrl+Alt+M` toggles the theme (Qt maps Ctrl to Cmd on macOS), and
`Edit > IDAPro-MuiLs Settings...` (`Ctrl+Alt+Shift+M`) opens the live-preview
settings where the OLED theme, fonts, accent and radius are chosen.

## Uninstall / full rollback

```bash
./scripts/macos/uninstall.sh                    # remove plugin + its settings
./scripts/macos/uninstall.sh --restore-backup   # ...and restore the latest backup, incl. ida.reg
./scripts/macos/uninstall.sh --keep-config      # remove plugin, keep ~/.idapro/modern_ui
```

Files the plugin owns: `~/.idapro/plugins/ida_modern_ui_loader.py`,
`~/.idapro/plugins/ida_modern_ui/`, `~/.idapro/modern_ui/config.json`,
`~/.idapro/modern_ui/startup.log`. Nothing else is written unless the
"Apply balanced panel layout" option is enabled, which then changes the
desktop stored by IDA (covered by the `ida.reg` backup).
