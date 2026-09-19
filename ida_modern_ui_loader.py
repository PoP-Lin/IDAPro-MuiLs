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
    from ida_modern_ui import RUNTIME_BUILD
    from ida_modern_ui.plugin import ModernUIPlugin

    _write_diagnostic(
        f"build={RUNTIME_BUILD} pid={os.getpid()} "
        f"module={ModernUIPlugin.__module__}\n",
    )
except Exception:
    _write_diagnostic(traceback.format_exc())
    raise


def PLUGIN_ENTRY():
    """IDA requires a zero-argument entry point defined in the loader module."""
    return ModernUIPlugin()


__all__ = ["PLUGIN_ENTRY"]
