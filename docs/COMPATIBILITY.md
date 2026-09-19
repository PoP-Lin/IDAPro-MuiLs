# IDA 9.3 and 9.4 compatibility preparation

The next development target is **Windows with IDA Pro 9.3 and 9.4**. Keep one
plugin package with shared code; introduce version-specific handling only when
an observed API or UI difference requires it.

| Environment | Current status |
| --- | --- |
| IDA Pro 9.3 on Windows 11 | Existing supported baseline; retain regression coverage |
| IDA Pro 9.4 on Windows | Preparation only; GUI runtime validation pending |

The published `v1.0.0` release remains the IDA 9.3 baseline. Preparing for 9.4
does not certify that release, or the development branch, for 9.4.

## Available development material and API comparison

The supplied `9.4.0-SDK/ida-sdk-windows` directory contains `idacli.exe`, compiled
sample plugins and processors, loaders, and configuration files. At the time of
inspection it contained no SDK interface headers, IDAPython runtime, Qt runtime,
or graphical `ida.exe`. The folder name alone does not establish its SDK/API
version. This directory alone is insufficient for a header/API comparison or GUI tests.

The additional `9.4.0-SDK/idapython-windows/python` directory supplies generated
IDAPython wrappers. Comparing these wrappers with the installed 9.3 wrappers
identified a new `UI_Hooks.about_to_exit(self)` callback. Existing UI hooks and
the `PluginForm.TWidgetToQtPythonWidget` signature remain available.

The development plugin registers early shutdown handling only when that callback
exists. It restores the theme, overlays, and native hooks while Qt is alive;
later `plugin_t.term()` calls are no-ops after successful cleanup. On 9.3,
the existing unload callback still performs cleanup. The shared plugin remains
usable with the 9.3 API rather than requiring the new event.

The wrapper comparison and simulated lifecycle tests do not validate the 9.4
native runtime or its widget painting. A maintainer or tester with a 9.4 GUI can
perform the remaining tests; existing users can continue using IDA 9.3.

Keep the local SDK directory out of Git and release archives. The plugin is
Python-based and does not need SDK binaries in its installation package.

## Collect comparable runtime inventories

For a tester with the graphical IDA 9.4 application and IDAPython available:

1. Use a disposable database and a separate IDA user directory for each version.
   Do not open a production 9.3 database in 9.4 for testing; use a copy.
2. Open Functions, Names, Strings, and Output in the same workspace on both
   versions. Open a representative third-party Qt panel if one is available.
3. Choose **File > Script file** and run
   `scripts/collect_ida_compatibility.py` from this source checkout.
4. Save each report separately. Compare `ida_version`, `ida_sdk_version`,
   `python_version`, `qt`, `missing_api`, `widget_classes`, `widget_inheritance`,
   and `builtin_panels`.

The collector records API availability, Qt class counts, and existing built-in
panel conversion results. It does not load/toggle the theme, open views, change
settings, or record database text, addresses, window titles, or user paths inside
the JSON. Third-party widget class names can appear; inspect reports before
sharing. The chosen report file is the only file the collector writes.

An empty `missing_api` list means the named attributes exist. It does **not**
prove callback signatures, visual appearance, plugin startup, or responsiveness.
Closed or localized panels can appear as `not_open_or_not_found`.

## Regression gates for both versions

Run the repository checks before testing in IDA:

```powershell
python scripts/run_checks.py --require-qt
python -m ruff check src scripts ida_modern_ui_loader.py --select E9,F63,F7,F82
```

Exercise each item in the real GUI on **both 9.3 and 9.4** before declaring dual
support:

- Automatic startup, settings preview/apply/cancel, theme off/on, and restart.
- Functions/Names/Strings continuous selection, outside-edge rounding, columns,
  quick filters, sorting, and scrolling.
- Output background, corners, command input, focus, and scrolling.
- G jump, Alt+T search, menus, context menus, and keyboard navigation.
- Docking, floating panels, saved layouts, and repeated window resizing at 100%
  and 150% display scaling.
- Representative third-party Qt panels and panels created after startup.
- No new exceptions; original theme restoration; isolated user configuration
  and registry-state checks.

Prefer capability checks for observed differences, and preserve the proven 9.3
behavior. Record the exact IDA, Python, PySide, and Qt versions for each run.
Do not infer IDA GUI support from SDK compilation or offline Qt checks alone.

## Release gate

Only update the supported-version tables and publish a new dual-version release
after both GUI runs pass. Keep the existing `v1.0.0` tag and assets available.
The testing package is `1.1.0-beta.1`, published as a GitHub prerelease. Its
distinct filename preserves the existing 1.0.0 release ZIP. The beta contains
the runtime exercised by the 9.3 GUI tests with an updated version marker;
it is available for 9.4 testing, not a claim of completed 9.4 GUI validation.
