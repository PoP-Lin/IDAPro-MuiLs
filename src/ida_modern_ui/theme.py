# -*- coding: utf-8 -*-
"""Theme rendering and application."""

from __future__ import annotations

import gc
import sys
from pathlib import Path

from . import palette

from .dock_runtime import (
    apply_dock_runtime,
    refresh_dock_runtime,
    restore_dock_runtime,
)
from .ida_widgets import apply_analysis_palette, repolish_analysis_widgets
from .native import (
    apply_native_appearance,
    refresh_native_window,
    restore_native_appearance,
)
from .navband_runtime import (
    apply_navband_runtime,
    refresh_navband_runtime,
    restore_navband_runtime,
)
from .panel_runtime import (
    apply_panel_runtime,
    refresh_panel_runtime,
    restore_panel_runtime,
)
from .plugin_panels import (
    apply_plugin_panel_runtime,
    refresh_plugin_panel_runtime,
    restore_plugin_panel_runtime,
)
from .popup_runtime import (
    apply_popup_runtime,
    refresh_popup_runtime,
    restore_popup_runtime,
)
from .qt_compat import QApplication, QEvent, QFontDatabase
from .resize_runtime import (
    apply_resize_runtime,
    refresh_resize_window,
    restore_resize_runtime,
)
from .selection_runtime import (
    apply_selection_runtime,
    refresh_selection_runtime,
    restore_selection_runtime,
)
from .scrollbar_runtime import (
    apply_scrollbar_runtime,
    refresh_scrollbar_runtime,
    restore_scrollbar_runtime,
)

THEMES_DIR = Path(__file__).resolve().parent / "themes"
STYLE_BEGIN = "/* BEGIN IDA Modern UI */"
STYLE_END = "/* END IDA Modern UI */"
STYLE_SEPARATOR = "\n\n"

IS_MACOS = sys.platform == "darwin"
CODE_FONT_FALLBACKS = (
    ("SF Mono", "Menlo", "JetBrainsMono Nerd Font Mono", "Monaco", "Courier New")
    if IS_MACOS
    else ("Cascadia Mono", "Consolas", "Courier New")
)
INTERFACE_FONT_FALLBACKS = (
    (".AppleSystemUIFont", "Helvetica Neue", "Helvetica", "Arial")
    if IS_MACOS
    else ("Segoe UI Variable", "Segoe UI", "Arial")
)
# Every theme renders from the authored dark stylesheet; palette.py derives
# the variants at apply time so the QSS and the Python runtimes never drift.
THEME_SOURCE = {"modern_dark": "modern_dark", "modern_oled": "modern_dark"}

DENSITY = {
    "compact": {"control_v": 3, "control_h": 7, "tab_v": 4, "tab_h": 8, "item": 2},
    "comfortable": {"control_v": 5, "control_h": 9, "tab_v": 6, "tab_h": 10, "item": 3},
}


class ThemeManager:
    def __init__(self):
        self._original_stylesheet: str | None = None
        self.enabled = False

    def apply(self, config: dict) -> None:
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("QApplication is not initialized")
        current_stylesheet = app.styleSheet()
        native_qss = self._without_own_stylesheet(current_stylesheet)
        # Refresh the baseline on every application.  This preserves a native
        # theme or third-party QSS change made while the plugin is enabled.
        self._original_stylesheet = native_qss

        theme_name = config["theme"]
        palette.set_theme(theme_name)
        qss_path = THEMES_DIR / f"{THEME_SOURCE.get(theme_name, 'modern_dark')}.qss"
        qss = palette.transform_text(qss_path.read_text(encoding="utf-8"))
        code_font = self._available_font(config["code_font_family"], CODE_FONT_FALLBACKS)
        interface_font = self._available_font(config["font_family"], INTERFACE_FONT_FALLBACKS)
        corner_radius = int(config["corner_radius"])
        panel_radius = 0 if corner_radius <= 0 else min(16, corner_radius + 2)
        panel_inner_radius = (
            0 if panel_radius <= 0 else max(2, panel_radius - 4)
        )
        values = {
            "ACCENT": config["accent"],
            "RADIUS": f"{corner_radius}px",
            "SMALL_RADIUS": f"{max(2, corner_radius - 2)}px",
            "CONTROL_RADIUS": f"{max(2, corner_radius - 3)}px",
            "PANEL_RADIUS": f"{panel_radius}px",
            "PANEL_INNER_RADIUS": f"{panel_inner_radius}px",
            "FONT_FAMILY": interface_font,
            "FONT_SIZE": f"{config['font_size']}pt",
            "CODE_FONT": code_font,
            "CLOSE_ICON": (THEMES_DIR / "icons" / "close.svg").as_posix(),
            "CLOSE_HOVER_ICON": (THEMES_DIR / "icons" / "close_hover.svg").as_posix(),
            "RADIO_OFF_ICON": (THEMES_DIR / "icons" / "radio_off.svg").as_posix(),
            "RADIO_ON_ICON": (THEMES_DIR / "icons" / "radio_on.svg").as_posix(),
            "RADIO_ON_DISABLED_ICON": (
                THEMES_DIR / "icons" / "radio_on_disabled.svg"
            ).as_posix(),
            "CHECK_ON_ICON": (THEMES_DIR / "icons" / "check_on.svg").as_posix(),
            "CHEVRON_DOWN_ICON": (
                THEMES_DIR / "icons" / "chevron_down.svg"
            ).as_posix(),
            "CHEVRON_RIGHT_ICON": (
                THEMES_DIR / "icons" / "chevron_right.svg"
            ).as_posix(),
            "CHEVRON_UP_ICON": (
                THEMES_DIR / "icons" / "chevron_up.svg"
            ).as_posix(),
            **{key.upper(): f"{value}px" for key, value in DENSITY[config["density"]].items()},
        }
        for key, value in values.items():
            qss = qss.replace(f"@{key}@", str(value))
        # IDA's own stylesheet contains qproperty values required by custom
        # viewers (disassembly, pseudocode, graph and output). Replacing it
        # makes those widgets fall back to bright defaults, so always layer our
        # visual rules on top of the native theme instead.
        # Keep the native stylesheet byte-for-byte so restore() returns IDA to
        # exactly the string it had before the theme was applied.
        themed_stylesheet = (
            f"{native_qss}{STYLE_SEPARATOR}{STYLE_BEGIN}\n{qss.rstrip()}\n{STYLE_END}\n"
        )
        if current_stylesheet != themed_stylesheet:
            app.setStyleSheet(themed_stylesheet)
        apply_popup_runtime(corner_radius)
        apply_panel_runtime()
        apply_plugin_panel_runtime(config.get("style_plugin_panels", True))
        # Qt's native QScrollBar complex-control paint path ignores
        # border-radius on the handle.  Paint a small, mouse-transparent
        # rounded overlay only for IDA-owned views; plugin panels remain
        # untouched by the scoped runtime.
        apply_scrollbar_runtime()
        # Functions is a native multi-column tree.  Keep its selected fill
        # continuous and round only the outer row edges in a post-paint pass;
        # plugin-owned trees are deliberately excluded by the runtime.
        apply_selection_runtime()
        # IDA's navigation band is a custom-painted widget; the local paint
        # overlay clips only that widget's visual rail and leaves its native
        # 32px hit area/layout intact.  Legend colour chips are tagged here
        # for a scoped rounded QSS rule.
        apply_navband_runtime(corner_radius=config.get("corner_radius", 0))
        apply_dock_runtime(config["accent"], config["corner_radius"])
        apply_analysis_palette()
        apply_native_appearance(dark=True, rounded=config["corner_radius"] > 0)
        apply_resize_runtime(config.get("smooth_resize", True))
        self.enabled = True

    @staticmethod
    def _available_font(preferred, fallbacks):
        try:
            available = {family.casefold(): family for family in QFontDatabase.families()}
        except TypeError:
            available = {
                family.casefold(): family for family in QFontDatabase().families()
            }
        for candidate in (preferred, *fallbacks):
            if candidate.casefold() in available:
                return available[candidate.casefold()]
        return fallbacks[-1]

    @staticmethod
    def _without_own_stylesheet(stylesheet):
        """Remove only this plugin's marked QSS block from a live stylesheet."""
        value = str(stylesheet or "")
        while True:
            start = value.find(STYLE_BEGIN)
            if start < 0:
                break
            end = value.find(STYLE_END, start + len(STYLE_BEGIN))
            if end < 0:
                # Leave an externally edited/incomplete block untouched rather
                # than deleting unrelated rules after a missing end marker.
                break
            head = value[:start]
            if head.endswith(STYLE_SEPARATOR):
                head = head[: -len(STYLE_SEPARATOR)]
            tail = value[end + len(STYLE_END):]
            if tail.startswith("\n"):
                tail = tail[1:]
            value = head + tail
        return value

    def restore(self) -> None:
        self.enabled = False
        restore_resize_runtime()
        restore_popup_runtime()
        restore_scrollbar_runtime()
        restore_selection_runtime()
        restore_navband_runtime()
        restore_dock_runtime()
        restore_panel_runtime()
        restore_plugin_panel_runtime()
        app = QApplication.instance()
        if app is not None:
            current_stylesheet = app.styleSheet()
            restored_stylesheet = self._without_own_stylesheet(current_stylesheet)
            if current_stylesheet != restored_stylesheet:
                app.setStyleSheet(restored_stylesheet)
                repolish_analysis_widgets()
        restore_native_appearance()
        palette.set_theme("modern_dark")

    def shutdown(self) -> None:
        """Restore, then destroy every Python-owned Qt object synchronously.

        IDA 9.4 on macOS (PySide 6.8, Python 3.14) crashes at exit if a
        PySide wrapper is still parented to a native widget, or a deferred
        delete is still queued, when the interpreter is finalised.  Flushing
        here, while Python is alive, keeps IDA's shutdown clean.
        """
        self.restore()
        app = QApplication.instance()
        if app is None:
            return
        try:
            deferred = getattr(getattr(QEvent, "Type", QEvent), "DeferredDelete")
            app.sendPostedEvents(None, deferred)
            app.processEvents()
            app.sendPostedEvents(None, deferred)
        except (AttributeError, RuntimeError, TypeError):
            pass
        gc.collect()

    def refresh_ida_widget(self, widget):
        if self.enabled and widget is not None:
            apply_analysis_palette(widget)
            refresh_panel_runtime(widget)
            refresh_plugin_panel_runtime(widget)
            refresh_scrollbar_runtime(widget)
            refresh_selection_runtime(widget)
            refresh_navband_runtime(widget)
            refresh_dock_runtime(widget)
            refresh_native_window(widget)
            refresh_resize_window(widget)
            refresh_popup_runtime()

    def refresh_ida_popup(self, owner, popup_handle):
        if self.enabled:
            refresh_popup_runtime(owner, popup_handle)
