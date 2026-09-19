#!/usr/bin/env python3
"""Offscreen regression checks for plugin-panel semantic role inference."""

from __future__ import annotations

import os
import py_compile
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "ida_modern_ui" / "plugin_panels.py"


def static_checks() -> None:
    raw = SOURCE.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SystemExit("PLUGIN_PANEL_ROLES_FAILED: UTF-8 BOM")
    text = raw.decode("utf-8")
    required = (
        "_is_embedded_line_editor",
        "QAbstractSpinBox",
        "QComboBox",
        "_has_search_semantics",
        "placeholderText",
        "accessibleName",
        "accessibleDescription",
    )
    missing = [token for token in required if token not in text]
    if missing:
        raise SystemExit("PLUGIN_PANEL_ROLES_FAILED: missing " + ", ".join(missing))
    py_compile.compile(str(SOURCE), doraise=True)


def qt_checks() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QSpinBox, QWidget
    except ImportError:
        from PyQt5.QtWidgets import QApplication, QComboBox, QLineEdit, QSpinBox, QWidget

    from ida_modern_ui.plugin_panels import (
        PANEL_PROPERTY,
        ROLE_PROPERTY,
        apply_plugin_panel_runtime,
        register_plugin_panel,
        restore_plugin_panel_runtime,
        unregister_plugin_panel,
    )

    app = QApplication.instance() or QApplication([])
    root = QWidget()
    register_plugin_panel(root)

    search = QLineEdit(root)
    search.setObjectName("symbolSearchEdit")
    filtered = QLineEdit(root)
    filtered.setPlaceholderText("Filter functions")
    find = QLineEdit(root)
    find.setAccessibleName("Find input")
    query = QLineEdit(root)
    query.setAccessibleDescription("Query symbols")

    ordinary = QLineEdit(root)
    ordinary.setObjectName("userNameEdit")
    setting = QLineEdit(root)
    setting.setObjectName("searchPathEdit")
    setting.setPlaceholderText("Directory containing indexes")

    combo = QComboBox(root)
    combo.setEditable(True)
    combo.lineEdit().setObjectName("searchEdit")
    combo.lineEdit().setPlaceholderText("Search choices")
    spin = QSpinBox(root)
    spin.lineEdit().setObjectName("queryInput")

    explicit = QLineEdit(root)
    explicit.setObjectName("searchEdit")
    explicit.setProperty(ROLE_PROPERTY, "muted")

    apply_plugin_panel_runtime(True)
    app.processEvents()

    for name, editor in {
        "object-name search": search,
        "placeholder filter": filtered,
        "accessible-name find": find,
        "accessible-description query": query,
    }.items():
        if editor.property(ROLE_PROPERTY) != "search":
            raise SystemExit(f"PLUGIN_PANEL_ROLES_FAILED: {name} was not inferred")
    for name, editor in {
        "ordinary setting": ordinary,
        "search-path setting": setting,
        "combo editor": combo.lineEdit(),
        "spin editor": spin.lineEdit(),
    }.items():
        if editor.property(ROLE_PROPERTY) is not None:
            raise SystemExit(f"PLUGIN_PANEL_ROLES_FAILED: {name} was misclassified")
    if explicit.property(ROLE_PROPERTY) != "muted":
        raise SystemExit("PLUGIN_PANEL_ROLES_FAILED: explicit role was overwritten")

    restore_plugin_panel_runtime()
    for editor in (search, filtered, find, query):
        if editor.property(ROLE_PROPERTY) is not None:
            raise SystemExit("PLUGIN_PANEL_ROLES_FAILED: inferred role survived restore")
    if explicit.property(ROLE_PROPERTY) != "muted":
        raise SystemExit("PLUGIN_PANEL_ROLES_FAILED: explicit role was not preserved")
    if root.property(PANEL_PROPERTY) is not None:
        raise SystemExit("PLUGIN_PANEL_ROLES_FAILED: panel mode survived restore")

    apply_plugin_panel_runtime(True)
    if search.property(ROLE_PROPERTY) != "search":
        raise SystemExit("PLUGIN_PANEL_ROLES_FAILED: role was not inferred after reapply")
    unregister_plugin_panel(root)
    if search.property(ROLE_PROPERTY) is not None:
        raise SystemExit("PLUGIN_PANEL_ROLES_FAILED: unregister did not restore descendants")
    if explicit.property(ROLE_PROPERTY) != "muted":
        raise SystemExit("PLUGIN_PANEL_ROLES_FAILED: unregister removed explicit role")

    restore_plugin_panel_runtime()
    root.close()
    print("PLUGIN_PANEL_ROLES_OK static=1 qt=1")


if __name__ == "__main__":
    static_checks()
    qt_checks()
