"""Static and optional Qt smoke checks for the rounded scrollbar runtime."""

from __future__ import annotations

import os
import py_compile
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "ida_modern_ui" / "scrollbar_runtime.py"


def static_checks() -> None:
    raw = SOURCE.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SystemExit("SCROLLBAR_RUNTIME_FAILED: UTF-8 BOM")
    text = raw.decode("utf-8")
    required = (
        "WA_TransparentForMouseEvents",
        "WA_TranslucentBackground",
        "QScrollBar",
        "QAbstractScrollArea",
        "modernUiPluginPanel",
        "border-radius",
        "apply_scrollbar_runtime",
        "restore_scrollbar_runtime",
    )
    missing = [token for token in required if token not in text]
    if missing:
        raise SystemExit(
            "SCROLLBAR_RUNTIME_FAILED: missing " + ", ".join(missing)
        )
    py_compile.compile(str(SOURCE), doraise=True)


def qt_smoke() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from PySide6.QtGui import QStandardItemModel
        from PySide6.QtWidgets import QApplication, QTableView, QWidget
    except ImportError:
        try:
            from PyQt5.QtGui import QStandardItemModel
            from PyQt5.QtWidgets import QApplication, QTableView, QWidget
        except ImportError:
            print("SCROLLBAR_RUNTIME_OK static_only=1")
            return

    from ida_modern_ui.scrollbar_runtime import (
        _qobject_key,
        _subcontrol_rect,
        apply_scrollbar_runtime,
        restore_scrollbar_runtime,
        scrollbar_runtime_diagnostics,
    )

    class tchooser_table_widget_t(QTableView):
        pass

    class plugin_panel_table(QTableView):
        pass

    app = QApplication.instance() or QApplication([])
    try:
        import shiboken6
    except ImportError:
        shiboken6 = None
    if shiboken6 is not None:
        probe = QWidget()
        if _qobject_key(probe)[0] != "cpp":
            raise SystemExit("SCROLLBAR_RUNTIME_FAILED: valid wrapper key missing")
        shiboken6.delete(probe)
        if shiboken6.isValid(probe):
            raise SystemExit("SCROLLBAR_RUNTIME_FAILED: wrapper deletion failed")
        if _qobject_key(probe) != ("python", id(probe)):
            raise SystemExit("SCROLLBAR_RUNTIME_FAILED: invalid wrapper guard missing")

    core = tchooser_table_widget_t()
    core.setModel(QStandardItemModel(120, 12))
    core.resize(240, 180)
    core.show()
    plugin = plugin_panel_table()
    plugin.setProperty("modernUiPluginPanel", True)
    plugin.setModel(QStandardItemModel(120, 12))
    plugin.resize(240, 180)
    plugin.show()
    app.processEvents()

    apply_scrollbar_runtime(core)
    apply_scrollbar_runtime(plugin)
    app.processEvents()
    diag = scrollbar_runtime_diagnostics()
    overlays = core.findChildren(QTableView)  # force wrapper creation on Qt5
    del overlays
    if diag["overlay_count"] != 2:
        raise SystemExit(
            "SCROLLBAR_RUNTIME_FAILED: expected 2 core overlays, got "
            + str(diag["overlay_count"])
        )
    if plugin.findChildren(type(core.verticalScrollBar()), "modernUiRoundedScrollbarOverlay"):
        raise SystemExit("SCROLLBAR_RUNTIME_FAILED: plugin panel was overlaid")

    before = core.verticalScrollBar().height()
    core.resize(240, 260)
    app.processEvents()
    overlay = core.findChildren(QWidget, "modernUiRoundedScrollbarOverlay")
    direct = [
        child
        for child in overlay
        if child.parent() is core.verticalScrollBar()
    ]
    if not direct or direct[0].geometry() != core.verticalScrollBar().rect():
        raise SystemExit("SCROLLBAR_RUNTIME_FAILED: resize geometry mismatch")
    if core.verticalScrollBar().height() <= before:
        raise SystemExit("SCROLLBAR_RUNTIME_FAILED: test resize did not apply")

    vertical = core.verticalScrollBar()
    native_handle = _subcontrol_rect(vertical)
    if native_handle is None or not native_handle.isValid():
        raise SystemExit("SCROLLBAR_RUNTIME_FAILED: handle rect missing")
    vertical.setSliderDown(True)
    direct[0].update()
    app.processEvents()
    pressed_image = direct[0].grab().toImage()
    pressed_pixel = pressed_image.pixelColor(native_handle.center()).name().upper()
    if pressed_pixel != "#60708A":
        raise SystemExit(
            "SCROLLBAR_RUNTIME_FAILED: pressed paint path not reached; pixel="
            + pressed_pixel
        )
    vertical.setSliderDown(False)
    vertical.setEnabled(False)
    app.processEvents()
    direct[0].update()
    app.processEvents()
    native_handle = _subcontrol_rect(vertical)
    if native_handle is None or not native_handle.isValid():
        raise SystemExit("SCROLLBAR_RUNTIME_FAILED: disabled handle rect missing")
    image = direct[0].grab().toImage()
    center = native_handle.center()
    disabled_pixel = image.pixelColor(center).name().upper()
    if disabled_pixel != "#2B333F":
        raise SystemExit(
            "SCROLLBAR_RUNTIME_FAILED: disabled paint path not reached; pixel="
            + disabled_pixel
        )
    vertical.setEnabled(True)

    restore_scrollbar_runtime()
    app.processEvents()
    if scrollbar_runtime_diagnostics()["overlay_count"]:
        raise SystemExit("SCROLLBAR_RUNTIME_FAILED: restore leaked overlays")
    core.close()
    plugin.close()
    print("SCROLLBAR_RUNTIME_OK static=1 qt=1")


if __name__ == "__main__":
    static_checks()
    qt_smoke()
