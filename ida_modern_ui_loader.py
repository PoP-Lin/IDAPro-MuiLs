# -*- coding: utf-8 -*-
"""IDAPro-MuiLs bootstrap and startup diagnostics."""

import os
import sys
import traceback
from pathlib import Path

import ida_diskio

PLUGIN_ROOT = Path(__file__).resolve().parent
LOG_PATH = Path(ida_diskio.get_user_idadir()) / "modern_ui" / "startup.log"

if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


def _write_diagnostic(text):
    """Logging is useful, but a read-only application folder must not block startup."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text(str(text), encoding="utf-8")
    except (OSError, RuntimeError, TypeError, ValueError):
        pass

try:
    import ida_pro

    # IDA 9.0+ (PySide6/Qt6).  Newer releases keep this API, so 9.5 and later
    # load the theme unchanged; anything older is skipped instead of raising.
    _IDA_VERSION = getattr(ida_pro, "IDA_SDK_VERSION", 900)
    if _IDA_VERSION < 900:
        raise ImportError(f"IDAPro-MuiLs needs IDA 9.0 or newer (found {_IDA_VERSION})")

    from ida_modern_ui import RUNTIME_BUILD
    from ida_modern_ui.plugin import ModernUIPlugin

    _write_diagnostic(
        f"build={RUNTIME_BUILD} pid={os.getpid()} "
        f"module={ModernUIPlugin.__module__}\n",
    )
except Exception:
    _write_diagnostic(traceback.format_exc())
    ModernUIPlugin = None


def PLUGIN_ENTRY():
    """IDA requires a zero-argument entry point defined in the loader module."""
    if ModernUIPlugin is None:
        import ida_idaapi

        class _Unavailable(ida_idaapi.plugin_t):
            flags = ida_idaapi.PLUGIN_HIDE
            comment = help = "IDAPro-MuiLs could not load; see modern_ui/startup.log"
            wanted_name = "IDAPro-MuiLs (unavailable)"
            wanted_hotkey = ""

            def init(self):
                return ida_idaapi.PLUGIN_SKIP

            def run(self, arg):
                return False

            def term(self):
                pass

        return _Unavailable()
    return ModernUIPlugin()


__all__ = ["PLUGIN_ENTRY"]
