#!/usr/bin/env python3
"""Qt lifecycle checks for reversible host quick-filter adjustments."""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT / "src"))

try:
    from PySide6.QtCore import QCoreApplication, QEvent, QSize
    from PySide6.QtGui import QColor, QIcon, QPixmap
    from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QWidget
except ImportError:
    from PyQt5.QtCore import QCoreApplication, QEvent, QSize
    from PyQt5.QtGui import QColor, QIcon, QPixmap
    from PyQt5.QtWidgets import QApplication, QLineEdit, QPushButton, QWidget

from ida_modern_ui import panel_runtime
from ida_modern_ui.qt_compat import qobject_key


class TChooser(QWidget):
    pass


class chooser_widget_t(QWidget):
    pass


class standalone_dirtree_widget_host_t(QWidget):
    pass


class quick_filter_widget_t(QWidget):
    pass


class quick_filter_input_t(QLineEdit):
    pass


def flush_deferred_deletes(app: QApplication) -> None:
    app.processEvents()
    deferred = getattr(getattr(QEvent, "Type", QEvent), "DeferredDelete")
    QCoreApplication.sendPostedEvents(None, deferred)
    app.processEvents()


def relay_count(editor: QLineEdit) -> int:
    return sum(
        type(child).__name__ == "_QuickFilterFocusRelay"
        for child in editor.children()
    )


def relay_qobject_count(app: QApplication) -> int:
    return sum(
        type(child).__name__ == "_QuickFilterHostRelay"
        for child in app.children()
    )


def margins_of(widget: QWidget) -> tuple[int, int, int, int]:
    margins = widget.contentsMargins()
    return (
        margins.left(),
        margins.top(),
        margins.right(),
        margins.bottom(),
    )


def assert_runtime_maps(expected_hosts: int, context: str) -> None:
    diagnostics = panel_runtime.panel_runtime_diagnostics()
    expected = {
        "quick_filter_focus_relay_count": 1 if expected_hosts else 0,
        "quick_filter_button_state_count": 1 if expected_hosts else 0,
        "quick_filter_host_relay_count": 1 if expected_hosts else 0,
        "quick_filter_host_watch_count": expected_hosts,
    }
    for name, value in expected.items():
        if diagnostics.get(name) != value:
            raise SystemExit(
                f"QUICK_FILTER_RUNTIME_FAILED: {context} {name} "
                f"expected={value} actual={diagnostics.get(name)}"
            )


def assert_invalid_wrapper_is_safe() -> None:
    """Exercise the PySide 6.8 crash guard without relying on event timing."""

    try:
        import shiboken6
    except ImportError:
        return

    probe = QWidget()
    if qobject_key(probe)[0] != "cpp":
        raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: valid wrapper key missing")
    shiboken6.delete(probe)
    if shiboken6.isValid(probe):
        raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: wrapper deletion failed")
    if qobject_key(probe) != ("python", id(probe)):
        raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: invalid wrapper guard missing")


def main() -> None:
    app = QApplication.instance() or QApplication([])
    assert_invalid_wrapper_is_safe()
    ordinary_host = QWidget()
    ordinary_surface = quick_filter_widget_t(ordinary_host)
    if panel_runtime._is_builtin_quick_filter(ordinary_surface):
        raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: arbitrary QWidget accepted")
    ordinary_host.deleteLater()
    flush_deferred_deletes(app)

    # IDA's widget_visible hook supplies the dirtree child, while the dynamic
    # quick filter is its sibling under the private host.  A subtree-only scan
    # misses that first Names instance, so exercise the real callback shape.
    panel_runtime.apply_panel_runtime()
    lifecycle_root = QWidget()
    lifecycle_host = standalone_dirtree_widget_host_t(lifecycle_root)
    lifecycle_tree = QWidget(lifecycle_host)
    lifecycle_surface = quick_filter_widget_t(lifecycle_host)
    lifecycle_button = QPushButton(lifecycle_surface)
    lifecycle_editor = quick_filter_input_t(lifecycle_surface)
    panel_runtime.refresh_panel_runtime(lifecycle_tree)
    lifecycle_diagnostics = panel_runtime.panel_runtime_diagnostics()
    if lifecycle_diagnostics.get("quick_filter_host_watch_count") != 1:
        raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: ancestor host was not watched")
    if not lifecycle_surface.testAttribute(panel_runtime._styled_background_attribute()):
        raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: sibling surface was not styled")
    if margins_of(lifecycle_surface) != (10, 0, 10, 3):
        raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: sibling margins missing")
    if relay_count(lifecycle_editor) != 1:
        raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: sibling focus relay missing")
    panel_runtime.restore_panel_runtime()
    lifecycle_root.deleteLater()
    flush_deferred_deletes(app)
    assert_runtime_maps(0, "ancestor sibling teardown")

    with warnings.catch_warnings(record=True) as lifecycle_warnings:
        warnings.simplefilter("always", RuntimeWarning)
        for iteration in range(50):
            host_class = (
                standalone_dirtree_widget_host_t,
                chooser_widget_t,
                TChooser,
            )[iteration % 3]
            host = host_class()
            host.resize(320, 56)

            # Register the empty host first. This makes the filter creation
            # below depend on the local ChildAdded relay, not the apply scan.
            panel_runtime.apply_panel_runtime()
            panel_runtime.apply_panel_runtime()
            flush_deferred_deletes(app)
            diagnostics = panel_runtime.panel_runtime_diagnostics()
            if diagnostics["quick_filter_host_watch_count"] != 1:
                raise SystemExit(
                    f"QUICK_FILTER_RUNTIME_FAILED: host watch at cycle {iteration}"
                )
            if diagnostics["quick_filter_host_pending_count"] != 0:
                raise SystemExit(
                    f"QUICK_FILTER_RUNTIME_FAILED: initial pending at cycle {iteration}"
                )

            surface = quick_filter_widget_t(host)
            surface.setGeometry(4, 4, 312, 46)
            original_margins = (2, 3, 4, 5)
            surface.setContentsMargins(*original_margins)
            button = QPushButton(surface)
            button.setGeometry(4, 4, 28, 34)
            editor = quick_filter_input_t(surface)
            editor.setGeometry(36, 4, 266, 34)

            original_pixmap = QPixmap(12, 10)
            original_pixmap.fill(QColor("#E06C75"))
            original_icon = QIcon(original_pixmap)
            original_icon_key = int(original_icon.cacheKey())
            original_icon_size = QSize(19, 17)
            button.setIcon(original_icon)
            button.setIconSize(original_icon_size)
            baseline_child_count = len(editor.children())

            # The surface remains hidden. A zero-delay pass must still see its
            # final meta-class and fully constructed input/button descendants.
            flush_deferred_deletes(app)
            if surface.isVisible():
                raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: hidden fixture visible")
            assert_runtime_maps(1, f"dynamic hidden cycle={iteration}")
            if not surface.testAttribute(panel_runtime._styled_background_attribute()):
                raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: styled background missing")
            if margins_of(surface) != (10, 0, 10, 3):
                raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: themed margins missing")
            if relay_count(editor) != 1:
                raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: focus relay missing")
            if button.iconSize() != QSize(14, 14):
                raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: themed icon size missing")
            if int(button.icon().cacheKey()) == original_icon_key:
                raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: themed icon was not applied")

            # Corrupt the cosmetic state and show only the host. Its local Show
            # relay must coalesce another pass and repair even a hidden filter.
            surface.setAttribute(panel_runtime._styled_background_attribute(), False)
            surface.setContentsMargins(7, 7, 7, 7)
            button.setIcon(original_icon)
            button.setIconSize(original_icon_size)
            surface.hide()
            host.show()
            flush_deferred_deletes(app)
            if surface.isVisible():
                raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: surface lost hidden state")
            if not surface.testAttribute(panel_runtime._styled_background_attribute()):
                raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: Show did not restyle surface")
            if margins_of(surface) != (10, 0, 10, 3):
                raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: Show did not restore margins")
            if button.iconSize() != QSize(14, 14):
                raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: Show did not restore icon")

            surface.show()
            editor.setFocus()
            flush_deferred_deletes(app)
            if surface.property("modernUiQuickFilterFocusWithin") is not True:
                raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: focus relay inactive")

            if iteration % 2 == 0:
                # Native panel teardown can precede theme teardown.
                host.deleteLater()
                flush_deferred_deletes(app)
                diagnostics = panel_runtime.panel_runtime_diagnostics()
                for name in (
                    "quick_filter_focus_relay_count",
                    "quick_filter_button_state_count",
                    "quick_filter_host_watch_count",
                ):
                    if diagnostics.get(name) != 0:
                        raise SystemExit(
                            f"QUICK_FILTER_RUNTIME_FAILED: destroy leaked {name} "
                            f"at cycle {iteration}"
                        )
                panel_runtime.restore_panel_runtime()
            else:
                # Theme teardown can precede native panel destruction.
                panel_runtime.restore_panel_runtime()
                flush_deferred_deletes(app)
                if relay_count(editor) != 0 or len(editor.children()) != baseline_child_count:
                    raise SystemExit(
                        f"QUICK_FILTER_RUNTIME_FAILED: relay QObject leaked at {iteration}"
                    )
                if int(button.icon().cacheKey()) != original_icon_key:
                    raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: icon not restored")
                if button.iconSize() != original_icon_size:
                    raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: icon size not restored")
                if margins_of(surface) != original_margins:
                    raise SystemExit("QUICK_FILTER_RUNTIME_FAILED: margins not restored")
                host.deleteLater()

            flush_deferred_deletes(app)
            assert_runtime_maps(0, f"teardown cycle={iteration}")
            if relay_qobject_count(app) != 0:
                raise SystemExit(
                    f"QUICK_FILTER_RUNTIME_FAILED: host relay QObject leaked at {iteration}"
                )

    if lifecycle_warnings:
        raise SystemExit(
            "QUICK_FILTER_RUNTIME_FAILED: RuntimeWarning during lifecycle "
            + str([str(item.message) for item in lifecycle_warnings])
        )

    print(
        "QUICK_FILTER_RUNTIME_OK cycles=50 dynamic_hidden=ChildAdded/Show "
        "hosts=standalone/chooser/TChooser host_relay=no_leak "
        "visible_root=ancestor_sibling "
        "icon=exact_restore focus_relay=no_leak "
        "margins=exact_restore warnings=0"
    )


if __name__ == "__main__":
    main()
