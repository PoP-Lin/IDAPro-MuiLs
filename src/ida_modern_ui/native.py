# -*- coding: utf-8 -*-
"""Low-frequency Windows DWM integration for IDA top-level windows."""

from __future__ import annotations

import ctypes
import sys
import weakref

from .qt_compat import QApplication, QObject

DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DEFAULT = 0
DWMWCP_ROUND = 2

_native_controller = None


def _apply_window(widget, dark, rounded):
    if sys.platform != "win32" or widget is None:
        return
    try:
        dwm = ctypes.windll.dwmapi
        handle = ctypes.c_void_p(int(widget.winId()))
        dark_value = ctypes.c_int(1 if dark else 0)
        corner_value = ctypes.c_int(DWMWCP_ROUND if rounded else DWMWCP_DEFAULT)
        result = dwm.DwmSetWindowAttribute(
            handle,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark_value),
            ctypes.sizeof(dark_value),
        )
        if result != 0:
            dwm.DwmSetWindowAttribute(
                handle,
                DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1,
                ctypes.byref(dark_value),
                ctypes.sizeof(dark_value),
            )
        dwm.DwmSetWindowAttribute(
            handle,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(corner_value),
            ctypes.sizeof(corner_value),
        )
        widget.update()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        pass


def _top_level_window(widget):
    """Resolve a focused/visible child to its native top-level window."""
    if widget is None:
        return None
    try:
        if widget.isWindow():
            return widget
        window = widget.window()
        if window is not None and window.isWindow():
            return window
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    return None


class _NativeAppearanceController(QObject):
    """Track windows through QApplication's low-frequency focus signal.

    A QApplication event filter would enter Python for every paint, resize and
    mouse event. IDA exposes newly-used windows through focusChanged, while
    ThemeManager.refresh_ida_widget covers newly-visible dock widgets. The
    combination keeps resize/paint paths entirely in native Qt code.
    """

    def __init__(self, app):
        super().__init__(app)
        self.enabled = False
        self.dark = True
        self.rounded = True
        self._connected = False
        self._windows = {}
        try:
            self._app_reference = weakref.ref(app)
        except TypeError:
            self._app_reference = None

    def owns(self, app):
        if self._app_reference is None:
            try:
                return self.parent() is app
            except (AttributeError, RuntimeError):
                return False
        try:
            return self._app_reference() is app
        except (RuntimeError, TypeError):
            return False

    def activate(self, app, dark, rounded):
        first_activation = not self.enabled
        self.dark = bool(dark)
        self.rounded = bool(rounded)
        self.enabled = True
        self._connect(app)

        if first_activation:
            # One complete scan per activation. Subsequent settings previews
            # update only the small weak-reference cache.
            try:
                windows = list(app.topLevelWidgets())
            except (AttributeError, RuntimeError, TypeError):
                windows = []
            for widget in windows:
                self.refresh(widget)
        else:
            self._refresh_known()

    def restore(self, app):
        if not self.enabled and not self._connected:
            return
        self.enabled = False
        self.dark = False
        self.rounded = False
        self._disconnect(app)

        # Include current top-level windows in case one never received focus or
        # an IDA widget-visible callback before the theme was restored.
        targets = list(self._live_windows())
        try:
            targets.extend(app.topLevelWidgets())
        except (AttributeError, RuntimeError, TypeError):
            pass
        seen = set()
        for widget in targets:
            key = id(widget)
            if key in seen:
                continue
            seen.add(key)
            _apply_window(widget, False, False)
        self._windows.clear()

    def refresh(self, widget):
        if not self.enabled:
            return
        window = _top_level_window(widget)
        if window is None:
            return
        self._remember(window)
        # Apply synchronously. Capturing an old theme state in a singleShot
        # callback caused stale rounded/dark attributes during rapid previews.
        _apply_window(window, self.dark, self.rounded)

    def _connect(self, app):
        if self._connected:
            return
        try:
            app.focusChanged.connect(self._focus_changed)
            self._connected = True
        except (AttributeError, RuntimeError, TypeError):
            self._connected = False

    def _disconnect(self, app):
        if not self._connected:
            return
        try:
            app.focusChanged.disconnect(self._focus_changed)
        except (AttributeError, RuntimeError, TypeError):
            pass
        self._connected = False

    def _focus_changed(self, _previous, current):
        self.refresh(current)

    def _remember(self, widget):
        key = id(widget)
        current = self._windows.get(key)
        if current is not None:
            try:
                if current() is widget:
                    return
            except (RuntimeError, TypeError):
                pass

        controller_reference = weakref.ref(self)

        def remove_dead(reference, window_key=key, owner=controller_reference):
            controller = owner()
            if controller is None:
                return
            record = controller._windows.get(window_key)
            if record is reference:
                controller._windows.pop(window_key, None)

        try:
            self._windows[key] = weakref.ref(widget, remove_dead)
        except TypeError:
            # Qt wrappers in supported IDA builds are weak-referenceable. If a
            # third-party wrapper is not, style it without retaining it.
            self._windows.pop(key, None)

    def _live_windows(self):
        stale = []
        for key, reference in list(self._windows.items()):
            try:
                widget = reference()
                if widget is None:
                    stale.append(key)
                else:
                    yield widget
            except (RuntimeError, TypeError):
                stale.append(key)
        for key in stale:
            self._windows.pop(key, None)

    def _refresh_known(self):
        for widget in list(self._live_windows()):
            _apply_window(widget, self.dark, self.rounded)


def apply_native_appearance(dark=True, rounded=True):
    """Enable native DWM styling without a QApplication event filter."""
    global _native_controller

    if sys.platform != "win32":
        return
    app = QApplication.instance()
    if app is None:
        return
    if _native_controller is None or not _native_controller.owns(app):
        _native_controller = _NativeAppearanceController(app)
    _native_controller.activate(app, dark, rounded)


def refresh_native_window(widget):
    """Refresh one visible IDA widget's enclosing native window."""
    if sys.platform != "win32" or _native_controller is None:
        return
    _native_controller.refresh(widget)


def restore_native_appearance():
    """Restore DWM defaults and disconnect the focusChanged hook."""
    if sys.platform != "win32" or _native_controller is None:
        return
    app = QApplication.instance()
    if app is None or not _native_controller.owns(app):
        return
    _native_controller.restore(app)


__all__ = [
    "apply_native_appearance",
    "refresh_native_window",
    "restore_native_appearance",
]
