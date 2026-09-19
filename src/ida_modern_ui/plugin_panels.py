# -*- coding: utf-8 -*-
"""Scoped styling bridge for Qt-based dockable plugin panels.

Application-wide QSS is useful for ordinary controls, but rounded table cards
and panel surfaces should not be forced onto every built-in custom viewer.
This module tags only compatible dock-content roots (or widgets explicitly
registered by a plugin).  The stylesheet can then use an ancestor property
selector, keeping third-party local styles higher in the cascade.

Discovery runs only at theme application and ``widget_visible`` lifecycle
events.  There is no timer, application event filter, paint hook, or resize
callback.
"""

from __future__ import annotations

import re

from .qt_compat import QApplication, QWidget


PANEL_PROPERTY = "modernUiPluginPanel"
ROLE_PROPERTY = "modernUiPanelRole"
OPT_IN_PROPERTY = "modernUiPluginPanelOptIn"
OPT_OUT_PROPERTY = "modernUiPluginPanelOptOut"

_ORIGINAL_MODE_PROPERTY = "_modernUiOriginalPluginPanelMode"
_ORIGINAL_ROLE_PROPERTY = "_modernUiOriginalPluginPanelRole"
_UNSET_SENTINEL = "__MODERN_UI_PROPERTY_UNSET__"
_PANEL_MODE = "adaptive"

_DOCK_PARENT_CLASSES = {"IDADockWidget", "DockWidget"}
_TITLE_CLASSES = {"DockWidgetTitle", "DockAreaDragTitle"}

# These are custom-painted/core analysis roots.  Their palettes and geometry
# are handled by dedicated selectors/modules rather than the plugin adapter.
_CORE_CONTENT_CLASSES = {
    "ConsoleWidget",
    "TChooser",
    "chooser_widget_t",
    "standalone_dirtree_widget_host_t",
    "standalone_dirtree_widget_t",
    "functions_dirtree_widget_t",
    "til_view_t",
    "GraphMiniView",
    "IDAViewHost",
    "listing_host_t",
    "CustomIDAMemo",
    "EAView",
    "text_area_t",
    "viewer_t",
    "navband_t",
    "TCpuRegs",
}

_VALID_ROLES = {
    "toolbar",
    "search",
    "tree",
    "table",
    "list",
    "header",
    "console",
    "surface",
    "empty",
    "badge",
    "muted",
}

_SEARCH_ROLE_WORDS = {"filter", "find", "query", "search"}
_SETTING_NAME_WORDS = {
    "directory",
    "endpoint",
    "folder",
    "limit",
    "option",
    "path",
    "preference",
    "setting",
    "template",
    "timeout",
    "url",
}
_EMBEDDED_EDITOR_CLASSES = {"QAbstractSpinBox", "QComboBox"}
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD_BOUNDARY = re.compile(r"[^a-z0-9]+")

_enabled = False
_scan_count = 0


def _meta_class_names(widget):
    try:
        meta = widget.metaObject()
        while meta is not None:
            yield str(meta.className())
            meta = meta.superClass()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return


def _text_value(widget, method_name):
    try:
        value = getattr(widget, method_name)()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return ""
    return str(value or "").strip()


def _semantic_words(value):
    separated = _CAMEL_BOUNDARY.sub(" ", str(value or ""))
    return tuple(word for word in _WORD_BOUNDARY.split(separated.casefold()) if word)


def _is_embedded_line_editor(widget):
    """Keep editors owned by compound controls under the compound role."""
    try:
        parent = widget.parentWidget()
        while parent is not None:
            if set(_meta_class_names(parent)).intersection(_EMBEDDED_EDITOR_CLASSES):
                return True
            parent = parent.parentWidget()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    return False


def _has_search_semantics(widget):
    """Recognize intentional search fields without styling every line edit."""
    object_words = set(_semantic_words(_text_value(widget, "objectName")))
    if object_words.intersection(_SEARCH_ROLE_WORDS):
        # Names such as ``searchPathEdit`` describe a setting value rather
        # than an interactive result filter.  Plugins can still opt these in
        # explicitly with set_plugin_panel_role().
        if not object_words.intersection(_SETTING_NAME_WORDS):
            return True

    # Placeholder and accessibility copy describe how the editor is used and
    # are therefore stronger signals than generic tooltips on settings forms.
    for method_name in ("placeholderText", "accessibleName", "accessibleDescription"):
        words = set(_semantic_words(_text_value(widget, method_name)))
        if words.intersection(_SEARCH_ROLE_WORDS):
            return True
    return False


def _truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _is_candidate_root(widget):
    if widget is None:
        return False
    try:
        if _truthy(widget.property(OPT_OUT_PROPERTY)):
            return False
        if _truthy(widget.property(OPT_IN_PROPERTY)):
            return True
        if widget.isWindow():
            return False
        names = set(_meta_class_names(widget))
        if names.intersection(_TITLE_CLASSES) or names.intersection(_CORE_CONTENT_CLASSES):
            return False
        parent = widget.parentWidget()
        if parent is None:
            return False
        if not set(_meta_class_names(parent)).intersection(_DOCK_PARENT_CLASSES):
            return False
        # IDAPython's dockable PluginForm is a stable, cooperative Qt boundary.
        # Unknown native/custom-painted dock roots remain untouched unless they
        # explicitly opt in through register_plugin_panel().
        return "PluginForm" in names
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _all_widgets():
    app = QApplication.instance()
    if app is None:
        return []
    try:
        return list(app.allWidgets())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return []


def _repolish(widget, include_children=True):
    widgets = [widget]
    if include_children:
        try:
            widgets.extend(widget.findChildren(QWidget))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    for candidate in widgets:
        try:
            style = candidate.style()
            style.unpolish(candidate)
            style.polish(candidate)
            candidate.update()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue


def _automatic_role(widget):
    names = set(_meta_class_names(widget))
    if "QToolBar" in names:
        return "toolbar"
    if "QTreeView" in names:
        return "tree"
    if "QTableView" in names:
        return "table"
    if "QListView" in names:
        return "list"
    if "QHeaderView" in names:
        return "header"
    if "QPlainTextEdit" in names or "QTextEdit" in names:
        return "console"
    if (
        "QLineEdit" in names
        and not _is_embedded_line_editor(widget)
        and _has_search_semantics(widget)
    ):
        return "search"
    return None


def _tag_role(widget, role):
    try:
        current = widget.property(ROLE_PROPERTY)
        # A plugin/API-authored semantic role owns the contract and takes
        # priority over structural standard-control classification.
        if current is not None:
            return False
        if widget.property(_ORIGINAL_ROLE_PROPERTY) is None:
            widget.setProperty(_ORIGINAL_ROLE_PROPERTY, _UNSET_SENTINEL)
        widget.setProperty(ROLE_PROPERTY, role)
        return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _tag_standard_roles(root):
    changed = False
    widgets = [root]
    try:
        widgets.extend(root.findChildren(QWidget))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    for widget in widgets:
        role = _automatic_role(widget)
        if role is not None and _tag_role(widget, role):
            changed = True
    return changed


def _tag(widget):
    try:
        current = widget.property(PANEL_PROPERTY)
        marker = widget.property(_ORIGINAL_MODE_PROPERTY)
        if marker is None:
            widget.setProperty(
                _ORIGINAL_MODE_PROPERTY,
                _UNSET_SENTINEL if current is None else current,
            )
        changed = False
        if str(current or "") != _PANEL_MODE:
            widget.setProperty(PANEL_PROPERTY, _PANEL_MODE)
            changed = True
        roles_changed = _tag_standard_roles(widget)
        if changed or roles_changed:
            _repolish(widget)
        return changed or roles_changed
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _restore_widget(widget, repolish=True):
    try:
        changed = False
        marker = widget.property(_ORIGINAL_MODE_PROPERTY)
        if marker is not None:
            widget.setProperty(
                PANEL_PROPERTY,
                None if marker == _UNSET_SENTINEL else marker,
            )
            widget.setProperty(_ORIGINAL_MODE_PROPERTY, None)
            changed = True
        role_marker = widget.property(_ORIGINAL_ROLE_PROPERTY)
        if role_marker is not None:
            widget.setProperty(
                ROLE_PROPERTY,
                None if role_marker == _UNSET_SENTINEL else role_marker,
            )
            widget.setProperty(_ORIGINAL_ROLE_PROPERTY, None)
            changed = True
        if changed and repolish:
            _repolish(widget, include_children=False)
        return changed
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def apply_plugin_panel_runtime(enabled=True):
    """Tag all existing compatible plugin-panel roots once."""
    global _enabled, _scan_count
    _enabled = bool(enabled)
    if not _enabled:
        restore_plugin_panel_runtime()
        return
    _scan_count += 1
    for widget in _all_widgets():
        if _is_candidate_root(widget):
            _tag(widget)


def refresh_plugin_panel_runtime(widget):
    """Tag one newly visible dock-content root."""
    if _enabled and _is_candidate_root(widget):
        _tag(widget)


def restore_plugin_panel_runtime():
    """Remove adapter properties and restore any pre-existing property value."""
    global _enabled
    _enabled = False
    for widget in _all_widgets():
        _restore_widget(widget)


def register_plugin_panel(widget):
    """Explicitly opt a Qt widget into the adaptive panel profile."""
    if widget is None:
        return False
    try:
        widget.setProperty(OPT_OUT_PROPERTY, None)
        widget.setProperty(OPT_IN_PROPERTY, True)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    if not _enabled:
        return True
    _tag(widget)
    try:
        return str(widget.property(PANEL_PROPERTY) or "") == _PANEL_MODE
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def unregister_plugin_panel(widget):
    """Opt a panel out and remove adapter-owned presentation properties."""
    if widget is None:
        return False
    restored = _restore_widget(widget, repolish=False)
    try:
        descendants = widget.findChildren(QWidget)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        descendants = []
    for descendant in descendants:
        restored = _restore_widget(descendant, repolish=False) or restored
    if restored:
        # The ancestor panel property participates in every adapter selector.
        # Re-evaluate the complete subtree once after all markers are restored,
        # rather than repeatedly repolishing children as each property changes.
        _repolish(widget, include_children=True)
    try:
        widget.setProperty(OPT_IN_PROPERTY, None)
        widget.setProperty(OPT_OUT_PROPERTY, True)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return restored
    return True


def set_plugin_panel_role(widget, role=None):
    """Assign or clear one of the documented semantic presentation roles."""
    if widget is None:
        return False
    candidate = str(role or "").strip().casefold()
    if candidate and candidate not in _VALID_ROLES:
        raise ValueError("Unknown plugin panel role: " + candidate)
    try:
        # This public call is a cooperative declaration, not runtime-owned
        # inference, so it remains available across a theme toggle.
        widget.setProperty(_ORIGINAL_ROLE_PROPERTY, None)
        widget.setProperty(ROLE_PROPERTY, candidate or None)
        _repolish(widget, include_children=False)
        return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def plugin_panel_diagnostics():
    tagged = 0
    explicit = 0
    roles = 0
    for widget in _all_widgets():
        try:
            if str(widget.property(PANEL_PROPERTY) or "") == _PANEL_MODE:
                tagged += 1
            if _truthy(widget.property(OPT_IN_PROPERTY)):
                explicit += 1
            if str(widget.property(ROLE_PROPERTY) or ""):
                roles += 1
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
    return {
        "enabled": bool(_enabled),
        "scan_count": int(_scan_count),
        "tagged_count": int(tagged),
        "explicit_count": int(explicit),
        "role_count": int(roles),
    }


__all__ = [
    "PANEL_PROPERTY",
    "ROLE_PROPERTY",
    "apply_plugin_panel_runtime",
    "plugin_panel_diagnostics",
    "refresh_plugin_panel_runtime",
    "register_plugin_panel",
    "restore_plugin_panel_runtime",
    "set_plugin_panel_role",
    "unregister_plugin_panel",
]
