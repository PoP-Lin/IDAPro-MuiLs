# -*- coding: utf-8 -*-
"""IDAPro-MuiLs package."""

__version__ = "1.1.0"
RUNTIME_BUILD = __version__


def register_plugin_panel(widget):
    from .plugin_panels import register_plugin_panel as register

    return register(widget)


def unregister_plugin_panel(widget):
    from .plugin_panels import unregister_plugin_panel as unregister

    return unregister(widget)


def set_plugin_panel_role(widget, role=None):
    from .plugin_panels import set_plugin_panel_role as set_role

    return set_role(widget, role)


__all__ = [
    "RUNTIME_BUILD",
    "__version__",
    "register_plugin_panel",
    "set_plugin_panel_role",
    "unregister_plugin_panel",
]
