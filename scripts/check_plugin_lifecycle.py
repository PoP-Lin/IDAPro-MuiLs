#!/usr/bin/env python3
"""Exercise 9.3 unload and 9.4 early-exit ordering with the real plugin class."""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
from types import ModuleType
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@contextmanager
def stub_ida_modules(modules):
    # patch.dict(sys.modules, ...) also removes modules imported in its scope.
    # Unloading/reimporting PySide6 extensions breaks Qt types on PySide 6.8.
    # Restore only the IDA stubs; leave Qt's native module lifetime intact.
    missing = object()
    original = {name: sys.modules.get(name, missing) for name in modules}
    sys.modules.update(modules)
    try:
        yield
    finally:
        for name, value in original.items():
            if value is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def check_lifecycle(early_exit, action_cleanup_fails=False):
    events = []
    qt_alive = [True]

    class Hooks:
        def hook(self):
            events.append("hook")

        def unhook(self):
            events.append("unhook")

    if early_exit:
        Hooks.about_to_exit = lambda self: None

    class Theme:
        enabled = False

        def apply(self, config):
            self.enabled = True
            events.append("apply")

        def restore(self):
            assert qt_alive[0], "cleanup touched Qt after destruction"
            self.enabled = False
            events.append("restore")

    def unregister(name):
        events.append("unregister")
        if action_cleanup_fails:
            raise RuntimeError("simulated action cleanup failure")

    kernwin = ModuleType("ida_kernwin")
    kernwin.UI_Hooks = Hooks
    kernwin.action_handler_t = object
    kernwin.action_desc_t = lambda *args: args
    kernwin.register_action = lambda descriptor: True
    kernwin.attach_action_to_menu = lambda *args: True
    kernwin.detach_action_from_menu = lambda *args: events.append("detach")
    kernwin.unregister_action = unregister
    kernwin.AST_ENABLE_ALWAYS = 1
    kernwin.SETMENU_APP = 1
    kernwin.msg = lambda text: None
    idaapi = ModuleType("ida_idaapi")
    idaapi.plugin_t = object
    idaapi.PLUGIN_FIX = 128
    idaapi.PLUGIN_KEEP = 2
    diskio = ModuleType("ida_diskio")

    with tempfile.TemporaryDirectory() as user_dir:
        diskio.get_user_idadir = lambda: user_dir
        modules = {"ida_kernwin": kernwin, "ida_idaapi": idaapi, "ida_diskio": diskio}
        with stub_ida_modules(modules):
            spec = importlib.util.spec_from_file_location(
                "ida_modern_ui._lifecycle_check", ROOT / "src/ida_modern_ui/plugin.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with patch.object(module, "ThemeManager", Theme), patch.object(
                module, "load_config", return_value={"enabled": True}
            ), patch.object(module, "save_config") as save, patch.object(
                module.ModernUIPlugin, "_report_runtime"
            ):
                plugin = module.ModernUIPlugin()
                assert plugin.init() == idaapi.PLUGIN_KEEP
                assert plugin._theme.enabled
                hooks = plugin._ui_hooks
                assert hasattr(hooks, "about_to_exit") == early_exit
                shutdown = hooks.about_to_exit if early_exit else plugin.term
                try:
                    shutdown()
                except RuntimeError:
                    if not action_cleanup_fails:
                        raise
                else:
                    assert not action_cleanup_fails, "expected action cleanup error"
                assert not plugin._theme.enabled
                assert plugin._ui_hooks is None
                # The host can unload PLUGIN_FIX after the 9.4 Qt exit event.
                qt_alive[0] = False
                plugin.term()
                plugin.term()
                assert events == ["hook", "apply", "unhook", "detach", "unregister", "restore"], events
                save.assert_not_called()


def main():
    check_lifecycle(early_exit=False)
    check_lifecycle(early_exit=True)
    check_lifecycle(early_exit=True, action_cleanup_fails=True)
    print("PLUGIN_LIFECYCLE_OK ida93_unload=1 ida94_early_exit=1 repeated_term=1 cleanup_error=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
