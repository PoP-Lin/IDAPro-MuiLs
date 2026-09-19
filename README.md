# IDAPro-MuiLs

[简体中文](README.zh-CN.md) | [English tutorial](docs/TUTORIAL.md)

[![CI](https://github.com/PoP-Lin/IDAPro-MuiLs/actions/workflows/ci.yml/badge.svg)](https://github.com/PoP-Lin/IDAPro-MuiLs/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-2ea44f.svg)](LICENSE)

A restrained, modern desktop theme for IDA Pro 9.3. It is implemented as an
IDAPython plugin and a scoped Qt stylesheet, so built-in views and compatible
third-party plugin panels keep their native behavior.

![IDAPro-MuiLs workspace](docs/images/overview.png)

## Highlights

- Starts automatically and remembers whether the theme is enabled.
- Styles menus, toolbars, tabs, docks, drag guides, tables, trees, scrollbars,
  Output, graph views, dialogs, quick filters, and Windows dark title bars.
- Keeps Functions, Names, and Strings selections continuous across all columns,
  with rounding only at the outside edges of the selected row.
- Gives Output, Strings, Names, and built-in project trees consistent inset
  surfaces without changing their models or interaction behavior.
- Detects compatible Qt plugin docks and applies scoped cards, searches,
  item views, consoles, status rows, and semantic panel roles.
- Supports interface font, code font, accent color, density, and corner-radius
  settings with live preview.
- Reduces intermediate workspace work during an OS resize gesture, then performs
  one complete layout and repaint when resizing ends.
- Restores IDA's original appearance without restarting the application.

## Compatibility

| Component | Supported |
| --- | --- |
| IDA Pro | 9.3 |
| IDAPython | Python 3.10 or 3.11 |
| Qt binding | PySide6 / Qt 6 |
| Supported OS | Windows 11, including 150% display scaling |

This release targets Windows 11. Its native title-bar and resize integrations
use Windows DWM APIs; Linux and macOS are not supported targets. The IDA SDK is
not required to install or develop this plugin.

The [v1.1.0-beta.1 prerelease](https://github.com/PoP-Lin/IDAPro-MuiLs/releases/tag/v1.1.0-beta.1)
prepares IDA 9.4 support while retaining 9.3 support. GUI validation for 9.4 is
pending; see the [compatibility plan](docs/COMPATIBILITY.md).

## Installation

### GitHub release

1. Close IDA.
2. Download `IDAPro-MuiLs-v1.0.0.zip` from the GitHub Releases page.
3. Extract the archive directly into IDA's `plugins` directory.
4. Start IDA.

To test the beta, download `IDAPro-MuiLs-v1.1.0-beta.1.zip` from the prerelease
page and use the same installation steps. Keep a copy of the current plugin
folder and loader before replacement. To roll back, close IDA, replace both
with that saved pair, and restart. The latest stable release remains v1.0.0.

The resulting layout must be:

```text
plugins/
|-- ida_modern_ui_loader.py
`-- ida_modern_ui/
    |-- plugin.py
    |-- themes/
    |-- project_docs/
    |   |-- CONTRIBUTING.md
    |   |-- LICENSE
    |   |-- README.md
    |   |-- README.zh-CN.md
    |   `-- docs/
    |       |-- TUTORIAL.md
    |       `-- images/
    |           `-- overview.png
    `-- ...
```

### Source checkout

Run the transactional installer from the repository root:

```powershell
.\scripts\install.ps1 -PluginsDirectory "C:\Path\To\IDA\plugins"
```

The installer stages and verifies both the loader and package. If replacement
fails, it restores the previous pair before returning an error. Restart IDA after
an update so Python modules and SVG resources are reloaded.

### Uninstall

Close IDA, then remove these two paths from its `plugins` directory:

```text
ida_modern_ui_loader.py
ida_modern_ui/
```

User preferences are stored separately under IDA's user configuration directory
in `modern_ui/config.json`. Remove that directory as well only when the saved
preferences are no longer needed.

## Usage

- `Ctrl+Alt+M`: toggle the theme and remember the state.
- `Ctrl+Alt+Shift+M`: open settings with live preview.
- `Edit > IDAPro-MuiLs Settings...`: open settings from the menu.

If another plugin uses `Ctrl+Alt+M` (for example, IDA MCP), use
`Edit > Plugins > IDAPro-MuiLs: Toggle` or assign a distinct shortcut in IDA.

## Plugin panel integration

Compatible dock-content roots are detected automatically. A plugin can opt in
explicitly and mark semantic children without depending on internal QSS:

```python
from ida_modern_ui import register_plugin_panel, set_plugin_panel_role

register_plugin_panel(panel_root)
set_plugin_panel_role(toolbar, "toolbar")
set_plugin_panel_role(search_edit, "search")
set_plugin_panel_role(result_tree, "tree")
set_plugin_panel_role(result_tree.header(), "header")
set_plugin_panel_role(log_console, "console")
set_plugin_panel_role(summary_frame, "surface")
set_plugin_panel_role(empty_label, "empty")
set_plugin_panel_role(count_label, "badge")
```

Standard toolbars, searches, tree/table/list views, headers, and text consoles
inside a detected panel receive those roles automatically. Explicit roles remain
intact across a theme toggle. The adapter does not change splitter ratios, layout
margins, row/header sizes, toolbar icon sizes, or widget-local stylesheets. Call
`unregister_plugin_panel(panel_root)` when a panel requires fully custom styling.

## Development

Install the optional CI dependencies, run all offline checks, and build a verified
release archive:

```powershell
python -m pip install -r requirements-ci.txt
python scripts/run_checks.py --require-qt
python -m ruff check src scripts ida_modern_ui_loader.py --select E9,F63,F7,F82
python scripts/build_release.py
```

The build command creates a reproducible ZIP and SHA256 file under `dist/`.
GitHub Actions runs the checks on Windows with Python 3.10 and 3.11. A `v1.0.0`
tag builds and publishes the matching release automatically.

## Repository layout

```text
IDAPro-MuiLs/
|-- .github/                 # CI, release workflow, and issue templates
|-- docs/images/             # Sanitized project screenshots
|-- scripts/                 # Installer, checks, and release builder
|-- src/ida_modern_ui/       # Runtime package, QSS, and icons
|-- ida_modern_ui_loader.py  # IDA plugin entry point
|-- CHANGELOG.md
|-- CONTRIBUTING.md
|-- LICENSE
`-- README.zh-CN.md
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and test expectations.
For a guided walkthrough, see the [English tutorial](docs/TUTORIAL.md).

## License and trademarks

IDAPro-MuiLs is released under the [MIT License](LICENSE).

This is an independent community project. It is not affiliated with or endorsed
by Hex-Rays. IDA and IDA Pro are trademarks of Hex-Rays SA.
