# -*- coding: utf-8 -*-
"""Low-frequency interactive-resize bridge for the main workspace.

Qt's raster backing store can spend most of an interactive resize waiting for
the Windows compositor, especially on HiDPI/high-refresh displays.  Repainting
the entire dock workspace for every intermediate size makes the native border
fall behind the pointer.  This module listens only for the two WinEvent
move/size boundary notifications, pauses Qt updates while the gesture is in
progress, and requests one complete repaint when it ends.

There is deliberately no QApplication event filter, resize-event hook, polling
timer, HWND subclass, or per-frame Python callback here.
"""

from __future__ import annotations

import ctypes

try:
    from ctypes import wintypes
except (ImportError, ValueError):  # non-Windows builds without wintypes
    wintypes = None
import os
import sys
import weakref

from .qt_compat import QApplication, QObject, QTimer


EVENT_SYSTEM_MOVESIZESTART = 0x000A
EVENT_SYSTEM_MOVESIZEEND = 0x000B
WINEVENT_OUTOFCONTEXT = 0x0000

# If Windows ever omits MOVESIZEEND (for example after an unusual shell
# interruption), never leave the workspace with updates disabled indefinitely.
_RECOVERY_TIMEOUT_MS = 15000

_resize_controller = None


def _meta_class_names(widget):
    try:
        meta = widget.metaObject()
        while meta is not None:
            yield str(meta.className())
            meta = meta.superClass()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return


def _main_window_for(widget):
    """Resolve a widget to IDA's main QMainWindow, excluding floating docks."""
    if widget is None:
        return None
    try:
        window = widget if widget.isWindow() else widget.window()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    if window is None:
        return None
    return window if "IDAMainWindow" in set(_meta_class_names(window)) else None


class _ResizeRuntimeController(QObject):
    """Own a process-local WinEvent hook for move/size start and end only."""

    def __init__(self, app):
        super().__init__(app)
        self.enabled = False
        self._hook = None
        self._callback = None
        self._user32 = None
        self._windows = {}
        self._frozen = {}
        self._generations = {}
        self.start_count = 0
        self.end_count = 0
        self.recovery_count = 0
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

    def activate(self, app):
        self.enabled = True
        try:
            windows = app.topLevelWidgets()
        except (AttributeError, RuntimeError, TypeError):
            windows = []
        for widget in windows:
            self.remember(widget)
        self._ensure_hook()

    def deactivate(self):
        self.enabled = False
        self._unhook()
        for handle in tuple(self._frozen):
            self._finish(handle, count_end=False)
        self._frozen.clear()
        self._generations.clear()
        self._windows.clear()

    def remember(self, widget):
        window = _main_window_for(widget)
        if window is None:
            return
        try:
            handle = int(window.winId())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return
        if not handle:
            return

        current = self._windows.get(handle)
        if current is window:
            self._ensure_hook()
            return

        # Keep the single main-window wrapper alive for the plugin lifetime.
        # PySide can garbage-collect a temporary wrapper returned by
        # topLevelWidgets() even though the C++ QMainWindow still exists; a
        # weak-only HWND cache would then silently stop matching resize events.
        # Qt still owns the C++ object, and every access below tolerates a
        # wrapper whose native object was destroyed during shutdown.
        self._windows[handle] = window
        self._ensure_hook()

    def diagnostics(self):
        self._prune_windows()
        return {
            "enabled": bool(self.enabled),
            "hook_installed": bool(self._hook),
            "window_count": len(self._windows),
            "frozen_count": len(self._frozen),
            "start_count": int(self.start_count),
            "end_count": int(self.end_count),
            "recovery_count": int(self.recovery_count),
        }

    def _prune_windows(self):
        stale = []
        for handle, window in tuple(self._windows.items()):
            try:
                if not window.isWindow() or int(window.winId()) != handle:
                    stale.append(handle)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                stale.append(handle)
        for handle in stale:
            self._windows.pop(handle, None)
            self._frozen.pop(handle, None)
            self._generations.pop(handle, None)

    def _ensure_hook(self):
        if (
            not self.enabled
            or self._hook
            or not self._windows
            or sys.platform != "win32"
        ):
            return
        try:
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            callback_type = ctypes.WINFUNCTYPE(
                None,
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.HWND,
                wintypes.LONG,
                wintypes.LONG,
                wintypes.DWORD,
                wintypes.DWORD,
            )
            self._callback = callback_type(self._win_event)
            self._user32.SetWinEventHook.argtypes = (
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HMODULE,
                callback_type,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
            )
            self._user32.SetWinEventHook.restype = wintypes.HANDLE
            self._user32.UnhookWinEvent.argtypes = (wintypes.HANDLE,)
            self._user32.UnhookWinEvent.restype = wintypes.BOOL
            self._user32.GetWindowThreadProcessId.argtypes = (
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD),
            )
            self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD

            first_handle = next(iter(self._windows))
            process_id = wintypes.DWORD()
            event_thread = self._user32.GetWindowThreadProcessId(
                wintypes.HWND(first_handle), ctypes.byref(process_id)
            )
            if not event_thread or int(process_id.value) != os.getpid():
                self._callback = None
                self._user32 = None
                return

            # Limit delivery to IDA's UI thread. The HWND cache below further
            # limits the action to IDAMainWindow, never dialogs or plugin docks.
            self._hook = self._user32.SetWinEventHook(
                EVENT_SYSTEM_MOVESIZESTART,
                EVENT_SYSTEM_MOVESIZEEND,
                None,
                self._callback,
                process_id.value,
                event_thread,
                WINEVENT_OUTOFCONTEXT,
            )
            if not self._hook:
                self._callback = None
                self._user32 = None
        except (AttributeError, OSError, TypeError, ValueError):
            self._hook = None
            self._callback = None
            self._user32 = None

    def _unhook(self):
        hook = self._hook
        user32 = self._user32
        self._hook = None
        if hook and user32 is not None:
            try:
                user32.UnhookWinEvent(hook)
            except (AttributeError, OSError, TypeError, ValueError):
                pass
        self._callback = None
        self._user32 = None

    def _win_event(
        self,
        _hook,
        event,
        hwnd,
        _object_id,
        _child_id,
        _event_thread,
        _event_time,
    ):
        if not self.enabled:
            return
        try:
            handle = int(hwnd or 0)
            if handle not in self._windows:
                return
            if int(event) == EVENT_SYSTEM_MOVESIZESTART:
                self._begin(handle)
            elif int(event) == EVENT_SYSTEM_MOVESIZEEND:
                self._finish(handle)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            # Never let a transient/deleted Qt wrapper escape through a native
            # callback boundary.
            return

    def _begin(self, handle):
        if handle in self._frozen:
            return
        window = self._windows.get(handle)
        if window is None:
            return
        try:
            restore_updates = bool(window.updatesEnabled())
            if restore_updates:
                window.setUpdatesEnabled(False)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

        layout = None
        restore_layout = False
        try:
            layout = window.layout()
            if layout is not None:
                restore_layout = bool(layout.isEnabled())
                if restore_layout:
                    # With paints already paused, intermediate dock/splitter
                    # geometry is also disposable.  Suspending the top-level
                    # layout removes the remaining resize cost while Windows
                    # keeps the outer frame tracking the pointer natively.
                    layout.setEnabled(False)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            layout = None
            restore_layout = False

        generation = self._generations.get(handle, 0) + 1
        self._generations[handle] = generation
        self._frozen[handle] = (
            window,
            restore_updates,
            layout,
            restore_layout,
            generation,
        )
        self.start_count += 1
        QTimer.singleShot(
            _RECOVERY_TIMEOUT_MS,
            lambda key=handle, token=generation: self._recover(key, token),
        )

    def _finish(self, handle, count_end=True):
        record = self._frozen.pop(handle, None)
        if record is None:
            return
        window, restore_updates, layout, restore_layout, _generation = record
        if layout is not None and restore_layout:
            try:
                layout.setEnabled(True)
                layout.invalidate()
                layout.activate()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if window is not None and restore_updates:
            try:
                window.setUpdatesEnabled(True)
                window.update()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if count_end:
            self.end_count += 1

    def _recover(self, handle, generation):
        record = self._frozen.get(handle)
        if record is None or record[4] != generation:
            return
        self.recovery_count += 1
        self._finish(handle, count_end=False)


def apply_resize_runtime(enabled=True):
    """Enable smooth interactive resizing for IDA's main workspace."""
    global _resize_controller

    if sys.platform != "win32" or not enabled:
        restore_resize_runtime()
        return
    app = QApplication.instance()
    if app is None:
        return
    if _resize_controller is None or not _resize_controller.owns(app):
        _resize_controller = _ResizeRuntimeController(app)
    _resize_controller.activate(app)


def refresh_resize_window(widget):
    """Remember a newly visible widget's enclosing main workspace."""
    if _resize_controller is None or not _resize_controller.enabled:
        return
    _resize_controller.remember(widget)


def restore_resize_runtime():
    if _resize_controller is not None:
        _resize_controller.deactivate()


def resize_runtime_diagnostics():
    if _resize_controller is None:
        return {
            "enabled": False,
            "hook_installed": False,
            "window_count": 0,
            "frozen_count": 0,
            "start_count": 0,
            "end_count": 0,
            "recovery_count": 0,
        }
    return _resize_controller.diagnostics()


__all__ = [
    "apply_resize_runtime",
    "refresh_resize_window",
    "resize_runtime_diagnostics",
    "restore_resize_runtime",
]
