# -*- coding: utf-8 -*-
"""Rounded native popup windows for IDA-owned menus.

Qt stylesheets paint rounded menu contents but do not clip a top-level popup
window on Windows.  This runtime registers only IDA's ``IdaMenu`` widgets.  It
uses the Windows 11 DWM corner preference when available and falls back to a
widget-local mask on older systems.  There is no application event filter,
resize callback, or paint interception.
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass, field
from typing import List, Any, Dict, Iterable, Optional

from .qt_compat import (
    QApplication,
    QMenu,
    QMenuBar,
    QPainterPath,
    QRectF,
    QRegion,
    QTimer,
    QWidget,
    qobject_key,
    same_qobject,
)


_PLUGIN_MARKER = "modernUiPluginPanel"
_PLUGIN_OPT_IN_MARKER = "modernUiPluginPanelOptIn"
_PLUGIN_OPT_OUT_MARKER = "modernUiPluginPanelOptOut"
_PLUGIN_FORM_CLASS = "PluginForm"
_IDA_MENU_CLASS = "IdaMenu"
_IDA_MAIN_WINDOW_CLASS = "IDAMainWindow"
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_DEFAULT = 0
_DWMWCP_ROUNDSMALL = 3


class _RTL_OSVERSIONINFOEXW(ctypes.Structure):
    _fields_ = (
        ("dwOSVersionInfoSize", ctypes.c_ulong),
        ("dwMajorVersion", ctypes.c_ulong),
        ("dwMinorVersion", ctypes.c_ulong),
        ("dwBuildNumber", ctypes.c_ulong),
        ("dwPlatformId", ctypes.c_ulong),
        ("szCSDVersion", ctypes.c_wchar * 128),
        ("wServicePackMajor", ctypes.c_ushort),
        ("wServicePackMinor", ctypes.c_ushort),
        ("wSuiteMask", ctypes.c_ushort),
        ("wProductType", ctypes.c_ubyte),
        ("wReserved", ctypes.c_ubyte),
    )


def _windows_build_number(
    platform_name: Optional[str] = None,
    rtl_loader: Any = None,
    fallback: Any = None,
) -> Optional[int]:
    """Return the real Windows build, with injectable probes for tests."""

    platform_name = os.name if platform_name is None else platform_name
    if platform_name != "nt":
        return None

    if rtl_loader is None:
        rtl_loader = lambda: ctypes.WinDLL("ntdll").RtlGetVersion
    try:
        rtl_get_version = rtl_loader()
        try:
            rtl_get_version.argtypes = (ctypes.c_void_p,)
            rtl_get_version.restype = ctypes.c_long
        except (AttributeError, TypeError, ValueError):
            pass
        version = _RTL_OSVERSIONINFOEXW()
        version.dwOSVersionInfoSize = ctypes.sizeof(version)
        if int(rtl_get_version(ctypes.byref(version))) == 0:
            build = int(version.dwBuildNumber)
            if build > 0:
                return build
    except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
        pass

    fallback = sys.getwindowsversion if fallback is None else fallback
    try:
        return int(fallback().build)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return None


def _meta_class_names(widget: Any) -> Iterable[str]:
    try:
        meta = widget.metaObject()
        while meta is not None:
            yield str(meta.className())
            meta = meta.superClass()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return


def _inherits(widget: Any, class_name: str) -> bool:
    return class_name in set(_meta_class_names(widget))


def _qobject_is_valid(value: Any) -> bool:
    if value is None:
        return False
    try:
        import shiboken6

        return bool(shiboken6.isValid(value))
    except ImportError:
        pass
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    try:
        import sip

        return not bool(sip.isdeleted(value))
    except ImportError:
        return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _has_plugin_marker(widget: Any) -> bool:
    current = widget
    for _ in range(16):
        if current is None:
            return False
        try:
            panel_marker = current.property(_PLUGIN_MARKER)
            if (
                _truthy(panel_marker)
                or str(panel_marker or "").strip().casefold() == "adaptive"
                or _truthy(current.property(_PLUGIN_OPT_IN_MARKER))
                or _truthy(current.property(_PLUGIN_OPT_OUT_MARKER))
                or _inherits(current, _PLUGIN_FORM_CLASS)
            ):
                return True
            current = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
    return False


def _is_ida_menu(widget: Any) -> bool:
    return (
        widget is not None
        and isinstance(widget, QMenu)
        and _inherits(widget, _IDA_MENU_CLASS)
        and not _has_plugin_marker(widget)
    )


def _copy_region(region: Any) -> Any:
    try:
        return QRegion(region)
    except (RuntimeError, TypeError, ValueError):
        return region


def _region_is_empty(region: Any) -> bool:
    try:
        return bool(region.isEmpty())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return True


def _rounded_region(width: int, height: int, radius: int) -> Any:
    width = max(0, int(width))
    height = max(0, int(height))
    radius = max(0, min(int(radius), width // 2, height // 2))
    if width <= 0 or height <= 0:
        return QRegion()
    if radius <= 0:
        return QRegion(0, 0, width, height)
    path = QPainterPath()
    path.addRoundedRect(
        QRectF(0.0, 0.0, float(width), float(height)),
        float(radius),
        float(radius),
    )
    return QRegion(path.toFillPolygon().toPolygon())


class _DwmCornerBackend:
    """Small ctypes wrapper kept replaceable for deterministic Qt tests."""

    def __init__(self) -> None:
        self._get = None
        self._set = None
        if os.name != "nt" or not self._is_windows_11():
            return
        try:
            from ctypes import wintypes

            library = ctypes.WinDLL("dwmapi")
            get_attribute = library.DwmGetWindowAttribute
            get_attribute.argtypes = (
                wintypes.HWND,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
            )
            get_attribute.restype = ctypes.c_long
            set_attribute = library.DwmSetWindowAttribute
            set_attribute.argtypes = get_attribute.argtypes
            set_attribute.restype = ctypes.c_long
            self._get = get_attribute
            self._set = set_attribute
        except (AttributeError, ImportError, OSError, TypeError, ValueError):
            self._get = None
            self._set = None

    @staticmethod
    def _is_windows_11() -> bool:
        build = _windows_build_number()
        return build is not None and build >= 22000

    def is_supported(self) -> bool:
        return self._set is not None

    def read(self, hwnd: int) -> Optional[int]:
        if self._get is None or not hwnd:
            return None
        value = ctypes.c_int(_DWMWCP_DEFAULT)
        try:
            result = self._get(
                int(hwnd),
                _DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        except (OSError, TypeError, ValueError):
            return None
        return int(value.value) if int(result) == 0 else None

    def write(self, hwnd: int, preference: int) -> bool:
        if self._set is None or not hwnd:
            return False
        value = ctypes.c_int(int(preference))
        try:
            result = self._set(
                int(hwnd),
                _DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        except (OSError, TypeError, ValueError):
            return False
        return int(result) == 0


_DWM_BACKEND = _DwmCornerBackend()


@dataclass
class _MenuEntry:
    menu: Any
    original_mask: Any
    original_mask_empty: bool
    before_show_callback: Any = None
    destroyed_callback: Any = None
    dwm_originals: Dict[int, int] = field(default_factory=dict)
    mask_applied: bool = False
    method: str = "pending"


@dataclass
class _MenuBarEntry:
    menu_bar: Any
    hovered_callback: Any = None
    destroyed_callback: Any = None


class _PopupRuntime:
    def __init__(self) -> None:
        self._enabled = False
        self._radius = 0
        self._entries: Dict[Any, _MenuEntry] = {}
        self._menu_bars: Dict[Any, _MenuBarEntry] = {}
        self._scan_count = 0
        self._deferred_scan_count = 0
        self._refresh_count = 0
        self._before_show_count = 0
        self._after_show_count = 0
        self._dwm_apply_count = 0
        self._mask_apply_count = 0
        self._plugin_skip_count = 0
        self._menubar_hover_count = 0
        self._timers: List[Any] = []

    def _later(self, msec: int, callback) -> None:
        """Owned single-shot timer that restore() can cancel.

        ``QTimer.singleShot(msec, callable)`` leaves a PySide-owned timer that
        segfaults IDA 9.4/macOS if the interpreter finalises before it fires.
        """
        timer = QTimer()
        timer.setSingleShot(True)
        timer.setInterval(max(0, int(msec)))
        timers = self._timers

        def fire():
            try:
                timers.remove(timer)
            except ValueError:
                pass
            callback()

        timer.timeout.connect(fire)
        timers.append(timer)
        timer.start()

    def _cancel_timers(self) -> None:
        for timer in list(self._timers):
            try:
                timer.stop()
                timer.timeout.disconnect()
            except (AttributeError, RuntimeError, TypeError):
                pass
        self._timers.clear()

    def apply(self, corner_radius: int) -> None:
        radius = max(0, int(corner_radius or 0))
        if (self._entries or self._menu_bars) and (
            not radius or radius != self._radius
        ):
            self._restore_entries()
            self._restore_menu_bars()
        self._enabled = True
        self._radius = radius
        self._scan_count += 1
        if not radius:
            return
        self._register_main_menu_tree()
        # PLUGIN_FIX can run before IDAMainWindow is exposed through Qt's
        # top-level inventory.  One event-loop callback catches that startup
        # boundary and only connects menu lifecycle signals; hidden menus stay
        # native-window-free until aboutToShow.
        self._later(0, self._refresh_main_menus_after_apply)
        self._later(750, self._refresh_main_menus_after_apply)

    def refresh(self, owner: Any = None, popup_handle: Any = None) -> int:
        if not self._enabled or not self._radius:
            return 0
        self._refresh_count += 1
        if owner is not None and _has_plugin_marker(owner):
            self._plugin_skip_count += 1
            return 0

        registered = 0
        if owner is None and popup_handle is None:
            registered += self._register_main_menu_tree()
        if _is_ida_menu(popup_handle):
            registered += int(self._register(popup_handle))
        for menu in self._visible_ida_menus():
            registered += int(self._register(menu))

        # TPopupMenu is opaque in IDAPython.  Once control returns to Qt the
        # newly populated popup is visible and can be identified safely by its
        # IdaMenu meta-class.  This is one local lifecycle callback, not a
        # polling timer or an application event filter.
        if popup_handle is not None:
            self._later(0, self._refresh_visible_after_popup)
        return registered

    def restore(self) -> None:
        self._enabled = False
        self._cancel_timers()
        self._restore_entries()
        self._restore_menu_bars()
        self._radius = 0

    def _restore_entries(self) -> None:
        for entry in list(self._entries.values()):
            self._restore_entry(entry)
        self._entries.clear()

    def _restore_menu_bars(self) -> None:
        for entry in list(self._menu_bars.values()):
            menu_bar = entry.menu_bar
            if not _qobject_is_valid(menu_bar):
                continue
            try:
                if entry.hovered_callback is not None:
                    menu_bar.hovered.disconnect(entry.hovered_callback)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            try:
                if entry.destroyed_callback is not None:
                    menu_bar.destroyed.disconnect(entry.destroyed_callback)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        self._menu_bars.clear()

    def _register_main_menu_tree(self) -> int:
        registered = 0
        for menu_bar in self._main_menubars():
            self._register_menu_bar(menu_bar)
        for menu in self._main_menubar_menus():
            registered += int(self._register(menu))
        return registered

    def _register_menu_bar(self, menu_bar: Any) -> bool:
        key = qobject_key(menu_bar)
        existing = self._menu_bars.get(key)
        if existing is not None:
            if not _qobject_is_valid(existing.menu_bar):
                self._menu_bars.pop(key, None)
                existing = None
        if existing is not None:
            try:
                if same_qobject(existing.menu_bar, menu_bar):
                    return False
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            self._menu_bars.pop(key, None)

        try:
            def hovered(action, entry_key=key):
                self._menubar_hovered(entry_key, action)

            def destroyed(_object=None, entry_key=key):
                self._menu_bars.pop(entry_key, None)

            entry = _MenuBarEntry(
                menu_bar=menu_bar,
                hovered_callback=hovered,
                destroyed_callback=destroyed,
            )
            self._menu_bars[key] = entry
            menu_bar.hovered.connect(hovered)
            menu_bar.destroyed.connect(destroyed)
            return True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self._menu_bars.pop(key, None)
            return False

    def _menubar_hovered(self, key: Any, action: Any) -> None:
        if not self._enabled or not self._radius or key not in self._menu_bars:
            return
        self._menubar_hover_count += 1
        try:
            self._register(action.menu())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

    def _register(self, menu: Any) -> bool:
        if not _is_ida_menu(menu):
            return False
        key = qobject_key(menu)
        existing = self._entries.get(key)
        if existing is not None:
            if not _qobject_is_valid(existing.menu):
                self._entries.pop(key, None)
                existing = None
        if existing is not None:
            try:
                if same_qobject(existing.menu, menu):
                    if menu.isVisible():
                        self._decorate(existing)
                    return False
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            self._restore_entry(existing)
            self._entries.pop(key, None)

        try:
            original_mask = _copy_region(menu.mask())
            entry = _MenuEntry(
                menu=menu,
                original_mask=original_mask,
                original_mask_empty=_region_is_empty(original_mask),
            )

            def before_show(entry_key=key):
                self._before_show(entry_key)

            def destroyed(_object=None, entry_key=key):
                self._entries.pop(entry_key, None)

            entry.before_show_callback = before_show
            entry.destroyed_callback = destroyed
            self._entries[key] = entry
            menu.aboutToShow.connect(before_show)
            menu.destroyed.connect(destroyed)
            if menu.isVisible():
                self._decorate(entry)
            return True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self._entries.pop(key, None)
            return False

    def _before_show(self, key: Any) -> None:
        if not self._enabled:
            return
        entry = self._entries.get(key)
        if entry is None:
            return
        self._before_show_count += 1
        self._decorate(entry, prefer_size_hint=True)
        self._later(0, lambda entry_key=key: self._after_show(entry_key))

    def _after_show(self, key: Any) -> None:
        if not self._enabled:
            return
        entry = self._entries.get(key)
        if entry is None:
            return
        self._after_show_count += 1
        self._decorate(entry)
        for menu in self._visible_ida_menus():
            self._register(menu)

    def _refresh_visible_after_popup(self) -> None:
        if not self._enabled:
            return
        for menu in self._visible_ida_menus():
            self._register(menu)

    def _refresh_main_menus_after_apply(self) -> None:
        if not self._enabled or not self._radius:
            return
        self._deferred_scan_count += 1
        self._register_main_menu_tree()

    def _decorate(self, entry: _MenuEntry, prefer_size_hint: bool = False) -> None:
        if not self._enabled or not self._radius:
            return
        menu = entry.menu
        try:
            hwnd = int(menu.winId())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            hwnd = 0

        if _DWM_BACKEND.is_supported() and hwnd:
            original = entry.dwm_originals.get(hwnd)
            if original is None:
                original = _DWM_BACKEND.read(hwnd)
            # DWM cannot clear an attribute back to an unknown value.  Keep
            # restoration exact by using the local mask path when reads fail.
            if original is not None and _DWM_BACKEND.write(hwnd, _DWMWCP_ROUNDSMALL):
                entry.dwm_originals.setdefault(hwnd, int(original))
                if entry.mask_applied:
                    self._restore_mask(entry)
                entry.method = "dwm"
                self._dwm_apply_count += 1
                return

        try:
            size = menu.sizeHint() if prefer_size_hint or not menu.isVisible() else menu.size()
            region = _rounded_region(size.width(), size.height(), self._radius)
            if _region_is_empty(region):
                return
            menu.setMask(region)
            entry.mask_applied = True
            entry.method = "mask"
            self._mask_apply_count += 1
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

    def _restore_mask(self, entry: _MenuEntry) -> None:
        try:
            if entry.original_mask_empty:
                entry.menu.clearMask()
            else:
                entry.menu.setMask(_copy_region(entry.original_mask))
            entry.mask_applied = False
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    def _restore_entry(self, entry: _MenuEntry) -> None:
        menu = entry.menu
        if not _qobject_is_valid(menu):
            entry.dwm_originals.clear()
            entry.mask_applied = False
            entry.method = "restored"
            return
        try:
            if entry.before_show_callback is not None:
                menu.aboutToShow.disconnect(entry.before_show_callback)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        try:
            if entry.destroyed_callback is not None:
                menu.destroyed.disconnect(entry.destroyed_callback)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        if entry.mask_applied:
            self._restore_mask(entry)
        for hwnd, preference in list(entry.dwm_originals.items()):
            _DWM_BACKEND.write(hwnd, preference)
        entry.dwm_originals.clear()
        entry.method = "restored"

    @staticmethod
    def _visible_ida_menus() -> Iterable[Any]:
        app = QApplication.instance()
        if app is None:
            return ()
        try:
            return tuple(
                widget
                for widget in app.topLevelWidgets()
                if _is_ida_menu(widget) and widget.isVisible()
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return ()

    @staticmethod
    def _main_menubars() -> Iterable[Any]:
        app = QApplication.instance()
        if app is None:
            return ()
        menu_bars = []
        seen_menu_bars = set()

        def collect_menu_bar(menu_bar: Any) -> None:
            if menu_bar is None or not isinstance(menu_bar, QMenuBar):
                return
            key = qobject_key(menu_bar)
            if key in seen_menu_bars:
                return
            try:
                owner = menu_bar.window()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return
            if not _inherits(owner, _IDA_MAIN_WINDOW_CLASS):
                return
            seen_menu_bars.add(key)
            menu_bars.append(menu_bar)

        try:
            # During PLUGIN_FIX startup IDAMainWindow may temporarily be absent
            # from topLevelWidgets(), while its QMenuBar is already present in
            # the application inventory.  Both paths are bounded one-shot
            # scans and still require an IDAMainWindow owner.
            for widget in app.allWidgets():
                collect_menu_bar(widget)
            for window in app.topLevelWidgets():
                if _inherits(window, _IDA_MAIN_WINDOW_CLASS):
                    collect_menu_bar(window.findChild(QMenuBar))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return tuple(menu_bars)
        return tuple(menu_bars)

    @classmethod
    def _main_menubar_menus(cls) -> Iterable[Any]:
        found = []
        seen = set()

        def collect(menu: Any) -> None:
            if not _is_ida_menu(menu):
                return
            key = qobject_key(menu)
            if key in seen:
                return
            seen.add(key)
            found.append(menu)
            try:
                for action in menu.actions():
                    collect(action.menu())
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass

        try:
            for menu_bar in cls._main_menubars():
                for action in menu_bar.actions():
                    collect(action.menu())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return tuple(found)
        return tuple(found)

    def diagnostics(self) -> Dict[str, Any]:
        methods = {"dwm": 0, "mask": 0, "pending": 0}
        for entry in self._entries.values():
            methods[entry.method] = methods.get(entry.method, 0) + 1
        return {
            "enabled": bool(self._enabled),
            "radius": int(self._radius),
            "registered_count": len(self._entries),
            "menubar_count": len(self._menu_bars),
            "dwm_count": methods.get("dwm", 0),
            "mask_count": methods.get("mask", 0),
            "pending_count": methods.get("pending", 0),
            "scan_count": int(self._scan_count),
            "deferred_scan_count": int(self._deferred_scan_count),
            "refresh_count": int(self._refresh_count),
            "before_show_count": int(self._before_show_count),
            "after_show_count": int(self._after_show_count),
            "dwm_apply_count": int(self._dwm_apply_count),
            "mask_apply_count": int(self._mask_apply_count),
            "plugin_skip_count": int(self._plugin_skip_count),
            "menubar_hover_count": int(self._menubar_hover_count),
            "application_event_filter": False,
            "resize_or_paint_hook": False,
        }


_runtime = _PopupRuntime()


def apply_popup_runtime(corner_radius: int) -> None:
    _runtime.apply(corner_radius)


def refresh_popup_runtime(owner: Any = None, popup_handle: Any = None) -> int:
    return _runtime.refresh(owner, popup_handle)


def restore_popup_runtime() -> None:
    _runtime.restore()


def popup_runtime_diagnostics() -> Dict[str, Any]:
    return _runtime.diagnostics()
