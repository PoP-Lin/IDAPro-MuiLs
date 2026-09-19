#!/usr/bin/env python3
"""Collect a read-only UI/API inventory from a running IDA GUI.

Run with File > Script file in IDA 9.3 or the prospective 9.4 installation.
This records capabilities, not a certification of visual compatibility.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import platform
import sys


REQUIRED_API = {
    "ida_diskio": ("get_user_idadir",),
    "ida_idaapi": ("plugin_t", "PLUGIN_FIX", "PLUGIN_KEEP"),
    "ida_kernwin": (
        "action_handler_t", "action_desc_t", "AST_ENABLE_ALWAYS", "SETMENU_APP",
        "UI_Hooks", "UI_Hooks.ready_to_run", "UI_Hooks.widget_visible",
        "UI_Hooks.desktop_applied", "UI_Hooks.finish_populating_widget_popup",
        "PluginForm.TWidgetToQtPythonWidget", "find_widget", "msg",
        "register_action", "unregister_action", "attach_action_to_menu",
        "detach_action_from_menu",
    ),
}
BUILTIN_PANELS = ("Functions", "Names", "Strings", "Output")


def resolve_attribute(value, name):
    for part in name.split("."):
        value = getattr(value, part)
    return value


def qt_runtime():
    # Match the plugin's supported bindings without importing or starting it.
    try:
        from PySide6 import QtCore, QtWidgets, __version__
        binding = "PySide6"
    except ImportError:
        from PyQt5 import QtCore, QtWidgets
        __version__ = QtCore.PYQT_VERSION_STR
        binding = "PyQt5"
    app = QtWidgets.QApplication.instance()
    if app is None or not isinstance(app, QtWidgets.QApplication):
        raise RuntimeError("Run this collector inside IDA's graphical application.")
    return app, {
        "binding": binding,
        "binding_version": __version__,
        "qt_version": QtCore.qVersion(),
    }


def class_chain(widget):
    result = []
    meta = widget.metaObject()
    while meta is not None:
        result.append(str(meta.className()))
        meta = meta.superClass()
    return result


def collect_report():
    """Inspect existing widgets without opening panels or changing the theme."""
    import ida_kernwin
    import ida_pro

    app, qt = qt_runtime()
    capabilities = {}
    for module_name, attributes in REQUIRED_API.items():
        module = importlib.import_module(module_name)
        for name in attributes:
            try:
                resolve_attribute(module, name)
                present = True
            except AttributeError:
                present = False
            capabilities[module_name + "." + name] = present

    direct_classes = Counter()
    inherited_classes = Counter()
    skipped_widgets = 0
    for widget in app.allWidgets():
        try:
            chain = class_chain(widget)
            direct_classes.update(chain[:1])
            inherited_classes.update(set(chain))
        except (RuntimeError, TypeError):
            skipped_widgets += 1

    panels = {}
    for name in BUILTIN_PANELS:
        try:
            native_widget = ida_kernwin.find_widget(name)
            if native_widget is None:
                panels[name] = {"status": "not_open_or_not_found"}
                continue
            widget = ida_kernwin.PluginForm.TWidgetToQtPythonWidget(native_widget)
            if widget is None:
                panels[name] = {"status": "qt_bridge_returned_none"}
                continue
            panels[name] = {
                "status": "found", "classes": class_chain(widget),
                "visible": widget.isVisible(),
                "device_pixel_ratio": widget.devicePixelRatioF(),
            }
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            # Error text can include private paths or panel contents.
            panels[name] = {"status": "inspection_error", "error_type": type(error).__name__}

    package = sys.modules.get("ida_modern_ui")
    return {
        "schema_version": 1,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "api_presence_and_existing_widgets_only",
        "ida_version": ida_kernwin.get_kernel_version(),
        "ida_sdk_version": getattr(ida_pro, "IDA_SDK_VERSION", None),
        "python_version": platform.python_version(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "qt": qt,
        "plugin": {
            "imported_version": getattr(package, "__version__", None),
            "runtime_build_marker": app.property("modern_ui_runtime_build"),
        },
        "required_api": capabilities,
        "missing_api": sorted(name for name, present in capabilities.items() if not present),
        "optional_api": {
            "ida_kernwin.UI_Hooks.about_to_exit": hasattr(ida_kernwin.UI_Hooks, "about_to_exit"),
        },
        "widget_classes": dict(sorted(direct_classes.items())),
        "widget_inheritance": dict(sorted(inherited_classes.items())),
        "skipped_invalid_widgets": skipped_widgets,
        "builtin_panels": panels,
        "limitations": [
            "API presence does not verify signatures, painting, performance, or compatibility.",
            "Missing panels/classes may mean the corresponding UI is closed or localized.",
            "The build marker is diagnostic metadata, not proof the theme is enabled.",
        ],
    }


def write_report(path):
    report = collect_report()
    target = Path(path)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main():
    import ida_kernwin

    version = ida_kernwin.get_kernel_version().replace(".", "-")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = ida_kernwin.ask_file(
        True, f"IDAPro-MuiLs-compatibility-{version}-{stamp}.json",
        "Save IDAPro-MuiLs compatibility inventory",
    )
    if target:
        report = write_report(target)
        ida_kernwin.msg(
            f"[IDAPro-MuiLs] Compatibility inventory saved: {target}\n"
            f"[IDAPro-MuiLs] Missing API symbols: {len(report['missing_api'])}; "
            "visual and interaction validation is still required.\n"
        )


if __name__ == "__main__":
    main()
