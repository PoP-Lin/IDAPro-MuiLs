"""Static and Qt smoke checks for the scoped popup runtime."""

from __future__ import annotations

import ctypes
import os
import py_compile
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "ida_modern_ui" / "popup_runtime.py"


def static_checks() -> None:
    raw = SOURCE.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SystemExit("POPUP_RUNTIME_FAILED: UTF-8 BOM")
    text = raw.decode("utf-8")
    required = (
        "DWMWA_WINDOW_CORNER_PREFERENCE",
        "DWMWCP_ROUNDSMALL",
        "RtlGetVersion",
        "QRegion",
        "IdaMenu",
        "IDAMainWindow",
        "aboutToShow",
        "menu_bar.hovered",
        "modernUiPluginPanel",
        "modernUiPluginPanelOptIn",
        "modernUiPluginPanelOptOut",
        "PluginForm",
        "apply_popup_runtime",
        "refresh_popup_runtime",
        "restore_popup_runtime",
        "deferred_scan_count",
    )
    missing = [token for token in required if token not in text]
    if missing:
        raise SystemExit("POPUP_RUNTIME_FAILED: missing " + ", ".join(missing))
    forbidden = (
        "QApplication.instance().installEventFilter",
        "def resizeEvent",
        "def paintEvent",
    )
    present = [token for token in forbidden if token in text]
    if present:
        raise SystemExit("POPUP_RUNTIME_FAILED: forbidden " + ", ".join(present))
    py_compile.compile(str(SOURCE), doraise=True)


def qt_smoke() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from PySide6.QtGui import QRegion
        from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QWidget
    except ImportError:
        try:
            from PyQt5.QtGui import QRegion
            from PyQt5.QtWidgets import QApplication, QMainWindow, QMenu, QWidget
        except ImportError:
            print("POPUP_RUNTIME_OK static_only=1")
            return

    from ida_modern_ui import popup_runtime

    rtl_calls = []
    fallback_calls = []

    def successful_rtl(version_pointer):
        rtl_calls.append(True)
        version = ctypes.cast(
            version_pointer,
            ctypes.POINTER(popup_runtime._RTL_OSVERSIONINFOEXW),
        ).contents
        version.dwBuildNumber = 22631
        return 0

    def forbidden_fallback():
        fallback_calls.append(True)
        raise RuntimeError("fallback must not run after a successful RtlGetVersion")

    build = popup_runtime._windows_build_number(
        platform_name="nt",
        rtl_loader=lambda: successful_rtl,
        fallback=forbidden_fallback,
    )
    if build != 22631 or len(rtl_calls) != 1 or fallback_calls:
        raise SystemExit("POPUP_RUNTIME_FAILED: RtlGetVersion was not preferred")

    class Version:
        build = 19045

    build = popup_runtime._windows_build_number(
        platform_name="nt",
        rtl_loader=lambda: (lambda _pointer: 1),
        fallback=lambda: Version(),
    )
    if build != 19045:
        raise SystemExit("POPUP_RUNTIME_FAILED: Windows build fallback failed")
    build = popup_runtime._windows_build_number(
        platform_name="nt",
        rtl_loader=lambda: (_ for _ in ()).throw(OSError("missing ntdll")),
        fallback=lambda: (_ for _ in ()).throw(RuntimeError("missing fallback")),
    )
    if build is not None:
        raise SystemExit("POPUP_RUNTIME_FAILED: failed build probes were not contained")
    if popup_runtime._windows_build_number(platform_name="posix") is not None:
        raise SystemExit("POPUP_RUNTIME_FAILED: non-Windows build was reported")

    class IDAMainWindow(QMainWindow):
        pass

    class IdaMenu(QMenu):
        pass

    class PluginForm(QWidget):
        pass

    class FakeDwm:
        def __init__(self, supported=True, fail_reads=False):
            self.supported = supported
            self.fail_reads = fail_reads
            self.values = {}
            self.writes = []

        def is_supported(self):
            return self.supported

        def read(self, hwnd):
            if self.fail_reads:
                return None
            return self.values.get(hwnd, 2)

        def write(self, hwnd, preference):
            if not self.supported:
                return False
            self.writes.append((int(hwnd), int(preference)))
            self.values[int(hwnd)] = int(preference)
            return True

    app = QApplication.instance() or QApplication([])
    original_backend = popup_runtime._DWM_BACKEND
    fake = FakeDwm()
    popup_runtime._DWM_BACKEND = fake

    main = IDAMainWindow()
    file_menu = IdaMenu("File", main)
    file_menu.setObjectName("File")
    submenu = IdaMenu("Load", file_menu)
    file_menu.addMenu(submenu)
    main.menuBar().addMenu(file_menu)
    main.show()

    custom = QMenu("Plugin-owned custom menu")
    plugin_owner = QWidget()
    plugin_owner.setProperty("modernUiPluginPanel", "adaptive")
    plugin_popup = IdaMenu("Plugin context")
    plugin_form_owner = PluginForm()
    plugin_form_popup = IdaMenu("PluginForm context")
    opted_out_owner = QWidget()
    opted_out_owner.setProperty("modernUiPluginPanelOptOut", True)
    opted_out_popup = IdaMenu("Opted-out context")
    builtin_owner = QWidget()
    builtin_popup = IdaMenu("Built-in context")
    app.processEvents()

    try:
        popup_runtime.apply_popup_runtime(10)
        diag = popup_runtime.popup_runtime_diagnostics()
        if (
            diag["registered_count"] != 2
            or diag["menubar_count"] != 1
            or diag["pending_count"] != 2
            or diag["dwm_count"] != 0
            or fake.writes
        ):
            raise SystemExit("POPUP_RUNTIME_FAILED: menubar discovery mismatch " + str(diag))
        file_action = next(
            action for action in main.menuBar().actions() if action.menu() is file_menu
        )
        main.menuBar().hovered.emit(file_action)
        diag = popup_runtime.popup_runtime_diagnostics()
        if diag["menubar_hover_count"] != 1 or fake.writes:
            raise SystemExit("POPUP_RUNTIME_FAILED: menubar hover was not lazy " + str(diag))
        file_menu.aboutToShow.emit()
        app.processEvents()
        file_hwnd = int(file_menu.winId())
        if fake.values.get(file_hwnd) != 3:
            raise SystemExit("POPUP_RUNTIME_FAILED: lazy DWM corner not applied")
        diag = popup_runtime.popup_runtime_diagnostics()
        if (
            diag["dwm_count"] != 1
            or diag["pending_count"] != 1
            or diag["deferred_scan_count"] < 1
        ):
            raise SystemExit("POPUP_RUNTIME_FAILED: lazy menu state mismatch " + str(diag))

        popup_runtime.refresh_popup_runtime(plugin_owner, plugin_popup)
        popup_runtime.refresh_popup_runtime(plugin_form_owner, plugin_form_popup)
        popup_runtime.refresh_popup_runtime(opted_out_owner, opted_out_popup)
        app.processEvents()
        diag = popup_runtime.popup_runtime_diagnostics()
        if diag["registered_count"] != 2 or diag["plugin_skip_count"] != 3:
            raise SystemExit("POPUP_RUNTIME_FAILED: plugin popup was not excluded")

        popup_runtime.refresh_popup_runtime(builtin_owner, builtin_popup)
        app.processEvents()
        diag = popup_runtime.popup_runtime_diagnostics()
        if diag["registered_count"] != 3:
            raise SystemExit("POPUP_RUNTIME_FAILED: built-in popup was not registered")
        if popup_runtime.qobject_key(custom) in popup_runtime._runtime._entries:
            raise SystemExit("POPUP_RUNTIME_FAILED: ordinary QMenu was registered")

        popup_runtime.restore_popup_runtime()
        if fake.values.get(file_hwnd) != 2:
            raise SystemExit("POPUP_RUNTIME_FAILED: DWM preference was not restored")
        diag = popup_runtime.popup_runtime_diagnostics()
        if diag["registered_count"] or diag["menubar_count"]:
            raise SystemExit("POPUP_RUNTIME_FAILED: restore leaked popup entries")

        fallback = FakeDwm(supported=False)
        popup_runtime._DWM_BACKEND = fallback
        original_mask = QRegion(1, 1, 40, 18)
        file_menu.resize(180, 120)
        file_menu.setMask(original_mask)
        popup_runtime.apply_popup_runtime(10)
        file_menu.aboutToShow.emit()
        app.processEvents()
        diag = popup_runtime.popup_runtime_diagnostics()
        if diag["mask_count"] < 1 or file_menu.mask() == original_mask:
            raise SystemExit("POPUP_RUNTIME_FAILED: QRegion fallback not applied " + str(diag))
        popup_runtime.restore_popup_runtime()
        if file_menu.mask() != original_mask:
            raise SystemExit("POPUP_RUNTIME_FAILED: original mask was not restored")

        # Never invent a DWM restore value when the original preference cannot
        # be read.  The local mask path remains reversible in that situation.
        read_failure = FakeDwm(supported=True, fail_reads=True)
        popup_runtime._DWM_BACKEND = read_failure
        file_menu.clearMask()
        popup_runtime.apply_popup_runtime(10)
        file_menu.aboutToShow.emit()
        app.processEvents()
        diag = popup_runtime.popup_runtime_diagnostics()
        if read_failure.writes or diag["mask_count"] < 1:
            raise SystemExit("POPUP_RUNTIME_FAILED: DWM read failure did not use mask")
        popup_runtime.restore_popup_runtime()
        if read_failure.writes or not file_menu.mask().isEmpty():
            raise SystemExit("POPUP_RUNTIME_FAILED: DWM read failure restore was not exact")
    finally:
        popup_runtime.restore_popup_runtime()
        popup_runtime._DWM_BACKEND = original_backend
        for widget in (
            builtin_popup,
            plugin_popup,
            plugin_form_popup,
            opted_out_popup,
            plugin_owner,
            plugin_form_owner,
            opted_out_owner,
            builtin_owner,
            custom,
            main,
        ):
            widget.close()
        app.processEvents()

    print("POPUP_RUNTIME_OK static=1 qt=1 dwm=apply/restore mask=fallback/restore scope=IdaMenu")


if __name__ == "__main__":
    static_checks()
    qt_smoke()
