#!/usr/bin/env python3
"""Static and optional offscreen smoke checks for the navigation-band polish."""

from __future__ import annotations

import os
import py_compile
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "ida_modern_ui" / "navband_runtime.py"
QSS = ROOT / "src" / "ida_modern_ui" / "themes" / "modern_dark.qss"


def static_checks() -> None:
    raw = SOURCE.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SystemExit("NAVBAND_RUNTIME_FAILED: UTF-8 BOM")
    text = raw.decode("utf-8")
    required = (
        "navband_t",
        "paint_over_navbar.py",
        "QPaintEvent",
        "installEventFilter",
        "_SwatchPaintFilter",
        "modernUiNavLegendSwatch",
        "apply_navband_runtime",
        "restore_navband_runtime",
    )
    missing = [token for token in required if token not in text]
    if missing:
        raise SystemExit("NAVBAND_RUNTIME_FAILED: missing " + ", ".join(missing))
    qss = QSS.read_text(encoding="utf-8")
    if 'ui_label_t[modernUiNavLegendSwatch="true"]' not in qss:
        raise SystemExit("NAVBAND_RUNTIME_FAILED: missing legend swatch selector")
    py_compile.compile(str(SOURCE), doraise=True)


def qt_smoke() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QColor, QPainter
        from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    except ImportError:
        try:
            from PyQt5.QtCore import QRect
            from PyQt5.QtGui import QColor, QPainter
            from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
        except ImportError:
            print("NAVBAND_RUNTIME_OK static_only=1")
            return

    from ida_modern_ui.navband_runtime import (
        apply_navband_runtime,
        navband_runtime_diagnostics,
        restore_navband_runtime,
    )

    class navband_t(QWidget):
        def paintEvent(self, event):  # noqa: N802 - Qt API
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor("#347FB1"))
            painter.fillRect(
                QRect(self.width() // 2, 0, self.width(), self.height()),
                QColor("#50A9A8"),
            )
            painter.end()

    class navigator_t(QWidget):
        pass

    class ui_label_t(QLabel):
        def paintEvent(self, event):  # noqa: N802 - Qt API
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor("#E07A5F"))
            painter.end()

    app = QApplication.instance() or QApplication([])
    root = navigator_t()
    root.setStyleSheet("navigator_t { background: #111319; }")
    layout = QVBoxLayout(root)
    layout.setContentsMargins(0, 0, 0, 0)
    band = navband_t()
    band.setFixedSize(120, 32)
    layout.addWidget(band)
    swatch = ui_label_t()
    swatch.setFixedSize(15, 15)
    layout.addWidget(swatch)
    root.resize(120, 60)
    root.show()
    app.processEvents()

    apply_navband_runtime()
    app.processEvents()
    diagnostics = navband_runtime_diagnostics()
    if diagnostics.get("navband_count") != 1:
        raise SystemExit("NAVBAND_RUNTIME_FAILED: fake navband was not attached")
    if diagnostics.get("legend_swatch_count") != 1:
        raise SystemExit("NAVBAND_RUNTIME_FAILED: legend swatch was not tagged")
    image = band.grab().toImage()
    # The outside corner is masked to the dark rail while the centre retains
    # the native segment colour.
    if image.pixelColor(0, 0).name().upper() != "#111319":
        raise SystemExit("NAVBAND_RUNTIME_FAILED: corner mask not applied")
    if image.pixelColor(60, 16).name().upper() not in {"#347FB1", "#50A9A8"}:
        raise SystemExit("NAVBAND_RUNTIME_FAILED: native segment was erased")
    swatch_image = swatch.grab().toImage()
    if swatch_image.pixelColor(0, 0).name().upper() != "#111319":
        raise SystemExit("NAVBAND_RUNTIME_FAILED: legend corner mask not applied")
    if swatch_image.pixelColor(7, 7).name().upper() != "#E07A5F":
        raise SystemExit("NAVBAND_RUNTIME_FAILED: legend colour was erased")
    restore_navband_runtime()
    app.processEvents()
    if swatch.property("modernUiNavLegendSwatch") is not None:
        raise SystemExit("NAVBAND_RUNTIME_FAILED: swatch marker not restored")
    print("NAVBAND_RUNTIME_OK")


if __name__ == "__main__":
    static_checks()
    qt_smoke()
