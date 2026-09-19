# IDAPro-MuiLs Tutorial

This guide walks through installation, first use, customization, plugin-panel
integration, maintenance, and development for IDAPro-MuiLs 1.0.0.

## 1. Requirements

- IDA Pro 9.3 with IDAPython and PySide6 enabled.
- Windows 11. Linux and macOS are not supported targets.
- Permission to write to IDA's `plugins` directory.

The IDA SDK is not required.

## 2. Install a release

1. Close every IDA process.
2. Download `IDAPro-MuiLs-v1.0.0.zip` and its `.sha256` file from Releases.
3. Verify the archive checksum in PowerShell:

   ```powershell
   (Get-FileHash .\IDAPro-MuiLs-v1.0.0.zip -Algorithm SHA256).Hash
   Get-Content .\IDAPro-MuiLs-v1.0.0.zip.sha256
   ```

4. Extract the ZIP directly into IDA's `plugins` directory. Do not add another
   wrapper directory.
5. Confirm the installed structure:

   ```text
   plugins/
   |-- ida_modern_ui_loader.py
   `-- ida_modern_ui/
       |-- __init__.py
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

6. Start IDA. The theme loads automatically.

## 3. Install from source

Clone the repository, close IDA, and run the transactional installer from the
repository root:

```powershell
git clone https://github.com/PoP-Lin/IDAPro-MuiLs.git
cd IDAPro-MuiLs
.\scripts\install.ps1 -PluginsDirectory "C:\Path\To\IDA\plugins"
```

The installer copies only public plugin files, verifies every installed SHA256,
and treats the loader and package as one transaction. If replacement fails, the
previous pair is restored.

## 4. First launch

After IDA opens:

1. Open `Edit > IDAPro-MuiLs Settings...`.
2. Keep **Enable theme on IDA startup** selected for automatic startup.
3. Choose an accent, interface font, code font, density, and corner radius.
4. Leave **Style compatible Qt plugin panels** selected unless a particular
   plugin intentionally owns every part of its appearance.
5. Select **Apply** to keep the dialog open or **OK** to apply and close it.

Changes preview immediately. **Cancel** restores the appearance that was active
when the dialog opened.

## 5. Keyboard and menu controls

- `Ctrl+Alt+M`: toggle the theme and save the enabled state.
- `Ctrl+Alt+Shift+M`: open the settings dialog.
- `Edit > IDAPro-MuiLs Settings...`: open settings from the menu.

Disabling the theme restores the native application stylesheet and the widget
properties retained by the runtime adapters.

## 6. Workspace behavior

The first compatible desktop receives a balanced editor/lower-panel layout.
After that migration, splitter positions belong to IDA's saved desktop and are
not continually forced by the plugin.

Functions, Names, and Strings use a continuous selected-row surface. Rounding is
drawn only at the outside edges of a row, so multi-column selections do not turn
into separate capsules. Output and built-in chooser views retain their native
models, keyboard navigation, and context menus.

## 7. Integrate a Qt plugin panel

Standard Qt plugin docks are detected automatically. For a custom panel, register
the content root and optionally assign semantic roles:

```python
from ida_modern_ui import (
    register_plugin_panel,
    set_plugin_panel_role,
    unregister_plugin_panel,
)

register_plugin_panel(panel_root)
set_plugin_panel_role(toolbar, "toolbar")
set_plugin_panel_role(search_edit, "search")
set_plugin_panel_role(result_tree, "tree")
set_plugin_panel_role(result_tree.header(), "header")
set_plugin_panel_role(log_console, "console")
set_plugin_panel_role(status_label, "muted")
```

Supported roles include `toolbar`, `search`, `tree`, `table`, `list`, `header`,
`console`, `surface`, `empty`, `badge`, and `muted`. The adapter deliberately
does not change splitter ratios, layout margins, row heights, header sizes,
toolbar icon sizes, or a widget's local stylesheet.

Call `unregister_plugin_panel(panel_root)` when the panel closes or when it must
return to a fully custom presentation.

## 8. Update or uninstall

To update, close IDA and repeat the release extraction or source installer. The
source installer removes stale modules and rolls back both the package and loader
if verification fails.

To uninstall, close IDA and remove:

```text
plugins/ida_modern_ui_loader.py
plugins/ida_modern_ui/
```

Saved preferences live under IDA's user configuration directory in
`modern_ui/config.json`. They can remain for a later reinstall.

## 9. Troubleshooting

### The theme does not appear

- Confirm both the loader file and package directory are directly under
  `plugins/`.
- Restart IDA after copying or updating files.
- Check `IDA_USER_DIRECTORY/modern_ui/startup.log` for an import traceback.
- Confirm the loader is UTF-8 without a byte-order mark.

### A third-party panel looks wrong

- Toggle **Style compatible Qt plugin panels** off to confirm the source.
- Ask the panel to call `unregister_plugin_panel()` if it requires a fully
  custom stylesheet.
- Include a sanitized screenshot and widget type information in a bug report.

### Resizing is still slow

- Confirm **Smooth window resizing** is enabled.
- Test with third-party panels closed to identify a panel doing expensive work
  on every resize event.
- Report display scaling, refresh rate, IDA version, and plugin version.

Never attach private databases, crash-memory dumps, licensed binaries, API keys,
or unsanitized diagnostic logs to a public issue.

## 10. Develop and package

Install the test dependencies and run the same checks used by GitHub Actions:

```powershell
python -m pip install -r requirements-ci.txt
python -m ruff check src scripts ida_modern_ui_loader.py --select E9,F63,F7,F82
python scripts\run_checks.py --require-qt
python scripts\build_release.py
```

The last command creates these ignored local artifacts:

```text
dist/IDAPro-MuiLs-v1.0.0.zip
dist/IDAPro-MuiLs-v1.0.0.zip.sha256
```

The builder rejects symbolic links and unsafe paths, fixes ZIP metadata for
reproducible output, reopens the archive, and compares every packaged byte with
the source tree. A Git tag such as `v1.0.0` must match `__version__`; the release
workflow verifies that match before publishing.
