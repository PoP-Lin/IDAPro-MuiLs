# -*- coding: utf-8 -*-
"""Scoped fixes for host panel styles that outrank application QSS.

The Output command line owns a local stylesheet containing a bare
``QGroupBox { border: 1px }`` rule.  A widget-local stylesheet outranks the
application theme, so QSS alone leaves a second rectangular frame around the
modern command controls.  This module touches only that exact built-in widget,
only during theme application/widget visibility, and restores its original
stylesheet when the theme is disabled.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .qt_compat import (
    QApplication,
    QEvent,
    QIcon,
    QObject,
    QSize,
    QTimer,
    Qt,
    QWidget,
    qobject_key,
    same_qobject,
)


_CLI_GROUP_STYLE = """
QGroupBox {
    border: 0;
    margin: 0;
    padding: 4px 8px;
    background: transparent;
    font-weight: 400;
}
QGroupBox::title {
    height: 0;
    margin: 0;
    padding: 0;
}
""".strip()
_ORIGINAL_STYLE_PROPERTY = "modern_ui_cli_original_stylesheet"
_HOST_CLI_GROUP_STYLE = "QGroupBox { border: 1px } "
_QUICK_FILTER_STYLED_PROPERTY = "modern_ui_quick_filter_original_styled_bg"
_QUICK_FILTER_MARGIN_PROPERTIES = (
    "modern_ui_quick_filter_margin_left",
    "modern_ui_quick_filter_margin_top",
    "modern_ui_quick_filter_margin_right",
    "modern_ui_quick_filter_margin_bottom",
)
_QUICK_FILTER_FOCUS_PROPERTY = "modernUiQuickFilterFocusWithin"
_QUICK_FILTER_ORIGINAL_FOCUS_PROPERTY = (
    "modern_ui_quick_filter_original_focus_within"
)
_QUICK_FILTER_PROPERTY_UNSET = "__MODERN_UI_QUICK_FILTER_PROPERTY_UNSET__"
_QUICK_FILTER_CLOSE_ICON = Path(__file__).resolve().parent / "themes" / "icons" / "close.svg"
_QUICK_FILTER_HOST_CLASSES = (
    "standalone_dirtree_widget_host_t",
    "chooser_widget_t",
    "TChooser",
)

# Output's native ``log_widget_t`` is a QTextEdit/QPlainTextEdit derivative.
# IDA leaves line wrapping disabled, which creates a second horizontal track
# inside the rounded card as soon as a diagnostic line exceeds the dock width.
# Keep the adjustment narrowly scoped to ConsoleWidget > log_widget_t and
# remember the exact native values so disabling the theme is lossless.
_OUTPUT_LOG_POLICY_PROPERTY = "modern_ui_output_log_original_hpolicy"
_OUTPUT_LOG_WRAP_PROPERTY = "modern_ui_output_log_original_wrap_mode"
_OUTPUT_LOG_BAR_VISIBLE_PROPERTY = "modern_ui_output_log_original_hbar_visible"
_OUTPUT_LOG_MARK_PROPERTY = "modern_ui_output_log_wrapped"

_enabled = False
_output_log_count = 0
_quick_filter_focus_relays = {}
_quick_filter_button_states = {}
_quick_filter_host_relay = None


@dataclass
class _QuickFilterButtonState:
    button: Any
    original_icon: Any
    original_icon_size: Any
    destroyed_signal: Any = None
    destroyed_callback: Any = None
    destroyed_connection: Any = None


@dataclass
class _QuickFilterHostState:
    host: Any
    destroyed_signal: Any = None
    destroyed_callback: Any = None
    destroyed_connection: Any = None


def _meta_class_names(widget):
    try:
        meta = widget.metaObject()
        while meta is not None:
            yield str(meta.className())
            meta = meta.superClass()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return


def _inherits(widget, class_name):
    return class_name in set(_meta_class_names(widget))


def _is_output_cli_group(widget):
    """Match only ConsoleWidget > CLIWidget > QGroupBox."""
    if not _inherits(widget, "QGroupBox"):
        return False
    try:
        parent = widget.parentWidget()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    if parent is None or not _inherits(parent, "CLIWidget"):
        return False

    current = parent
    for _ in range(4):
        try:
            current = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        if current is None:
            return False
        if _inherits(current, "ConsoleWidget"):
            return True
    return False


def _styled_background_attribute():
    group = getattr(Qt, "WidgetAttribute", Qt)
    return getattr(group, "WA_StyledBackground")


def _event_type(name):
    holder = getattr(QEvent, "Type", QEvent)
    return getattr(holder, name)


_CHILD_ADDED_EVENT = _event_type("ChildAdded")
_SHOW_EVENT = _event_type("Show")


def _repolish(widget):
    try:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def _set_quick_filter_focus(surface, focused):
    try:
        value = bool(focused)
        if surface.property(_QUICK_FILTER_FOCUS_PROPERTY) == value:
            return
        surface.setProperty(_QUICK_FILTER_FOCUS_PROPERTY, value)
        _repolish(surface)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


class _QuickFilterFocusRelay(QObject):
    """Mirror an editor's focus onto its rounded quick-filter surface."""

    def __init__(self, editor, surface):
        super().__init__(editor)
        self.editor = editor
        self.surface = surface
        self.destroyed_signal = None
        self.destroyed_callback = None
        self.destroyed_connection = None

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        try:
            if not same_qobject(watched, self.editor):
                return False
            kind = event.type()
            if kind == _event_type("FocusIn"):
                _set_quick_filter_focus(self.surface, True)
            elif kind == _event_type("FocusOut"):
                _set_quick_filter_focus(self.surface, False)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        return False


def _is_builtin_quick_filter(widget):
    """Match IDA-owned chooser/tree quick filters, never plugin line edits."""
    if not _inherits(widget, "quick_filter_widget_t"):
        return False
    try:
        parent = widget.parentWidget()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    if parent is None:
        return False
    if _inherits(parent, "standalone_dirtree_widget_host_t"):
        return True
    # Names, Imports, Exports, cross-reference lists, and plugin-created IDA
    # choosers all use the host's quick_filter_widget_t surface.  Matching the
    # private host class keeps arbitrary plugin QLineEdits out while giving
    # every chooser the same focus relay, inset, and single-frame contract.
    return _inherits(parent, "chooser_widget_t") or _inherits(parent, "TChooser")


def _is_quick_filter_host(widget):
    """Match only IDA chooser hosts that directly own a quick filter."""
    return any(_inherits(widget, name) for name in _QUICK_FILTER_HOST_CLASSES)


def _quick_filter_host_ancestor(widget):
    """Return the nearest supported host for an IDA lifecycle root.

    ``widget_visible`` commonly supplies the chooser's tree rather than its
    private host.  The quick-filter surface is a sibling of that tree, so a
    descendant-only refresh cannot see it.  Keep this lookup bounded and stop
    at the first private IDA host; arbitrary plugin ancestors remain excluded.
    """

    current = widget
    for _ in range(12):
        if current is None:
            break
        if _is_quick_filter_host(current):
            return current
        try:
            current = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            break
    return None


def _disconnect_signal(signal, callback, handle):
    if handle is not None:
        try:
            QObject.disconnect(handle)
            return
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    if signal is None or callback is None:
        return
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Failed to disconnect.*",
                category=RuntimeWarning,
            )
            signal.disconnect(callback)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


class _QuickFilterHostRelay(QObject):
    """Observe deferred quick-filter creation on a small set of local hosts."""

    def __init__(self, parent):
        super().__init__(parent)
        self.enabled = True
        self._hosts = {}
        self._pending_hosts = {}
        self._timer_scheduled = False

    @property
    def host_count(self):
        return len(self._hosts)

    @property
    def pending_count(self):
        return len(self._pending_hosts)

    def activate(self):
        self.enabled = True

    def watch(self, host):
        if not self.enabled or not _is_quick_filter_host(host):
            return
        try:
            key = qobject_key(host)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return
        current = self._hosts.get(key)
        if current is not None:
            try:
                if same_qobject(current.host, host):
                    self._schedule(host)
                    return
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            self._unwatch(key, current)

        state = _QuickFilterHostState(host=host)
        try:
            host.installEventFilter(self)

            def destroyed(_object=None, host_key=key):
                self._hosts.pop(host_key, None)
                self._pending_hosts.pop(host_key, None)

            state.destroyed_signal = host.destroyed
            state.destroyed_callback = destroyed
            state.destroyed_connection = host.destroyed.connect(destroyed)
            self._hosts[key] = state
            self._schedule(host)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            try:
                host.removeEventFilter(self)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            self._hosts.pop(key, None)
            self._pending_hosts.pop(key, None)

    def deactivate(self):
        self.enabled = False
        states = tuple(self._hosts.items())
        self._hosts.clear()
        self._pending_hosts.clear()
        self._timer_scheduled = False
        for key, state in states:
            self._unwatch(key, state)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        if not self.enabled:
            return False
        try:
            kind = event.type()
            if kind not in {_CHILD_ADDED_EVENT, _SHOW_EVENT}:
                return False
            key = qobject_key(watched)
            state = self._hosts.get(key)
            if state is None or not same_qobject(state.host, watched):
                return False
            # ChildAdded is delivered while the derived child is still only a
            # QWidget.  Queue one coalesced pass so the final IDA meta-class and
            # its input/button children are available, even when it stays hidden.
            self._schedule(watched)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        return False

    def _schedule(self, host):
        if not self.enabled:
            return
        try:
            key = qobject_key(host)
            state = self._hosts.get(key)
            if state is None or not same_qobject(state.host, host):
                return
            self._pending_hosts[key] = host
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return
        if self._timer_scheduled:
            return
        self._timer_scheduled = True
        try:
            QTimer.singleShot(0, self._flush_pending)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self._timer_scheduled = False
            self._flush_pending()

    def _flush_pending(self):
        self._timer_scheduled = False
        pending = tuple(self._pending_hosts.items())
        self._pending_hosts.clear()
        if not self.enabled:
            return
        for key, host in pending:
            state = self._hosts.get(key)
            try:
                if state is None or not same_qobject(state.host, host):
                    continue
                _refresh_quick_filter_host(host)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                if self._hosts.get(key) is state:
                    self._hosts.pop(key, None)

    def _unwatch(self, key, state):
        if self._hosts.get(key) is state:
            self._hosts.pop(key, None)
        self._pending_hosts.pop(key, None)
        try:
            state.host.removeEventFilter(self)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        _disconnect_signal(
            state.destroyed_signal,
            state.destroyed_callback,
            state.destroyed_connection,
        )


def _ensure_quick_filter_host_relay(app):
    global _quick_filter_host_relay
    relay = _quick_filter_host_relay
    if relay is not None:
        try:
            if relay.parent() is app:
                relay.activate()
                return relay
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        try:
            relay.deactivate()
            relay.deleteLater()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    _quick_filter_host_relay = _QuickFilterHostRelay(app)
    return _quick_filter_host_relay


def _is_output_log(widget):
    """Match only IDA's Output log, never plugin-owned text editors."""
    if not _inherits(widget, "log_widget_t"):
        return False
    current = widget
    for _ in range(6):
        try:
            current = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        if current is None:
            return False
        if _inherits(current, "ConsoleWidget"):
            return True
    return False


def _scrollbar_off_policy(widget):
    """Resolve Qt's ScrollBarAlwaysOff across PySide/PyQt enum layouts."""
    try:
        from . import qt_compat as _qt_compat

        qt = getattr(_qt_compat, "Qt", None)
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        qt = None
    enum_holder = getattr(qt, "ScrollBarPolicy", qt)
    holders = (
        getattr(qt, "ScrollBarAlwaysOff", None),
        getattr(enum_holder, "ScrollBarAlwaysOff", None),
        getattr(widget, "ScrollBarAlwaysOff", None),
    )
    return next((value for value in holders if value is not None), None)


def _widget_width_wrap_mode(widget):
    """Resolve QTextEdit/QPlainTextEdit's WidgetWidth enum lazily."""
    holders = (
        getattr(widget, "LineWrapMode", None),
        getattr(type(widget), "LineWrapMode", None),
        widget,
        type(widget),
    )
    for holder in holders:
        if holder is None:
            continue
        try:
            value = getattr(holder, "WidgetWidth")
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
        if value is not None:
            return value
    # Qt's enum value is stable (1) for WidgetWidth in both bindings.  This
    # fallback is only for IDA's older generated wrappers with no enum object.
    return 1


def _apply_output_log_surface(widget):
    """Wrap Output lines and remove its redundant horizontal scrollbar."""
    global _output_log_count
    if not _is_output_log(widget):
        return False
    try:
        marked = str(widget.property(_OUTPUT_LOG_MARK_PROPERTY) or "")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        marked = ""
    if marked == "v1":
        return False
    try:
        if widget.property(_OUTPUT_LOG_POLICY_PROPERTY) is None:
            widget.setProperty(
                _OUTPUT_LOG_POLICY_PROPERTY,
                widget.horizontalScrollBarPolicy(),
            )
        if widget.property(_OUTPUT_LOG_WRAP_PROPERTY) is None:
            getter = getattr(widget, "lineWrapMode", None)
            original_wrap = getter() if getter is not None else None
            widget.setProperty(_OUTPUT_LOG_WRAP_PROPERTY, original_wrap)
        if widget.property(_OUTPUT_LOG_BAR_VISIBLE_PROPERTY) is None:
            bar = widget.horizontalScrollBar()
            visible_getter = getattr(bar, "isVisible", None) if bar is not None else None
            original_visible = bool(visible_getter()) if visible_getter is not None else False
            widget.setProperty(_OUTPUT_LOG_BAR_VISIBLE_PROPERTY, original_visible)

        mode = _widget_width_wrap_mode(widget)
        setter = getattr(widget, "setLineWrapMode", None)
        if setter is not None:
            setter(mode)
        policy = _scrollbar_off_policy(widget)
        if policy is not None:
            widget.setHorizontalScrollBarPolicy(policy)
        bar = widget.horizontalScrollBar()
        if bar is not None:
            bar.hide()
        widget.setProperty(_OUTPUT_LOG_MARK_PROPERTY, "v1")
        widget.updateGeometry()
        widget.update()
        _output_log_count += 1
        return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _restore_output_log_surface(widget):
    if not _is_output_log(widget):
        return
    try:
        marked = str(widget.property(_OUTPUT_LOG_MARK_PROPERTY) or "")
        if not marked:
            return
        original_wrap = widget.property(_OUTPUT_LOG_WRAP_PROPERTY)
        if original_wrap is not None:
            setter = getattr(widget, "setLineWrapMode", None)
            if setter is not None:
                setter(original_wrap)
        original_policy = widget.property(_OUTPUT_LOG_POLICY_PROPERTY)
        if original_policy is not None:
            widget.setHorizontalScrollBarPolicy(original_policy)
        original_visible = widget.property(_OUTPUT_LOG_BAR_VISIBLE_PROPERTY)
        bar = widget.horizontalScrollBar()
        if bar is not None and original_visible is not None:
            if bool(original_visible):
                bar.show()
            else:
                bar.hide()
        widget.setProperty(_OUTPUT_LOG_MARK_PROPERTY, None)
        widget.setProperty(_OUTPUT_LOG_WRAP_PROPERTY, None)
        widget.setProperty(_OUTPUT_LOG_POLICY_PROPERTY, None)
        widget.setProperty(_OUTPUT_LOG_BAR_VISIBLE_PROPERTY, None)
        widget.updateGeometry()
        widget.update()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def _remember_and_style(widget):
    try:
        original = widget.property(_ORIGINAL_STYLE_PROPERTY)
        if original is None:
            current = str(widget.styleSheet())
            # A binding wrapper can be recreated while the underlying host
            # widget keeps our stylesheet.  Preserve the known host baseline
            # rather than recording our own rule as its restore target.
            original = (
                _HOST_CLI_GROUP_STYLE
                if current.strip() == _CLI_GROUP_STYLE
                else current
            )
            widget.setProperty(_ORIGINAL_STYLE_PROPERTY, original)
        widget.setStyleSheet(_CLI_GROUP_STYLE)
        widget.updateGeometry()
        widget.update()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return


def _enable_quick_filter_surface(widget):
    """Let a plain QWidget paint its scoped QSS card background."""
    try:
        attribute = _styled_background_attribute()
        original = widget.property(_QUICK_FILTER_STYLED_PROPERTY)
        if original is None:
            original = bool(widget.testAttribute(attribute))
            widget.setProperty(_QUICK_FILTER_STYLED_PROPERTY, original)
        if widget.property(_QUICK_FILTER_MARGIN_PROPERTIES[0]) is None:
            margins = widget.contentsMargins()
            originals = (
                int(margins.left()),
                int(margins.top()),
                int(margins.right()),
                int(margins.bottom()),
            )
            for name, value in zip(_QUICK_FILTER_MARGIN_PROPERTIES, originals):
                widget.setProperty(name, value)
        widget.setAttribute(attribute, True)
        # The native filter lays out its clear button at x=0.  QSS margins only
        # inset painting, not child geometry, so mirror the card inset in the
        # QWidget contents rectangle to keep X + input inside one pill.
        widget.setContentsMargins(10, 0, 10, 3)
        widget.updateGeometry()
        widget.update()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return


def _quick_filter_buttons(surface):
    try:
        return [
            child
            for child in surface.findChildren(QWidget)
            if _inherits(child, "QPushButton")
            and same_qobject(child.parentWidget(), surface)
        ]
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return []


def _enable_quick_filter_buttons(surface):
    """Apply the muted clear icon while retaining exact host-owned values."""
    for button in _quick_filter_buttons(surface):
        key = qobject_key(button)
        state = _quick_filter_button_states.get(key)
        if state is not None:
            try:
                if same_qobject(state.button, button):
                    button.setIcon(QIcon(str(_QUICK_FILTER_CLOSE_ICON)))
                    button.setIconSize(QSize(14, 14))
                    continue
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            _restore_quick_filter_button(key, state)
        try:
            state = _QuickFilterButtonState(
                button=button,
                original_icon=QIcon(button.icon()),
                original_icon_size=QSize(button.iconSize()),
            )

            def destroyed(_object=None, button_key=key):
                _quick_filter_button_states.pop(button_key, None)

            state.destroyed_signal = button.destroyed
            state.destroyed_callback = destroyed
            state.destroyed_connection = button.destroyed.connect(destroyed)
            _quick_filter_button_states[key] = state
            button.setIcon(QIcon(str(_QUICK_FILTER_CLOSE_ICON)))
            button.setIconSize(QSize(14, 14))
            button.update()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _quick_filter_button_states.pop(key, None)


def _restore_quick_filter_button(key, state):
    _quick_filter_button_states.pop(key, None)
    _disconnect_signal(
        state.destroyed_signal,
        state.destroyed_callback,
        state.destroyed_connection,
    )
    try:
        state.button.setIcon(QIcon(state.original_icon))
        state.button.setIconSize(QSize(state.original_icon_size))
        state.button.update()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def _restore_quick_filter_buttons():
    for key, state in tuple(_quick_filter_button_states.items()):
        _restore_quick_filter_button(key, state)


def _quick_filter_inputs(surface):
    try:
        return [
            child
            for child in surface.findChildren(QWidget)
            if _inherits(child, "quick_filter_input_t")
        ]
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return []


def _enable_quick_filter_focus(surface):
    """Install one local focus relay per accepted built-in filter editor."""
    if not _is_builtin_quick_filter(surface):
        return
    try:
        original = surface.property(_QUICK_FILTER_ORIGINAL_FOCUS_PROPERTY)
        if original is None:
            current = surface.property(_QUICK_FILTER_FOCUS_PROPERTY)
            surface.setProperty(
                _QUICK_FILTER_ORIGINAL_FOCUS_PROPERTY,
                _QUICK_FILTER_PROPERTY_UNSET if current is None else current,
            )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return

    for editor in _quick_filter_inputs(surface):
        key = qobject_key(editor)
        existing = _quick_filter_focus_relays.get(key)
        if existing is not None:
            try:
                if same_qobject(existing.editor, editor):
                    existing.surface = surface
                    _set_quick_filter_focus(surface, editor.hasFocus())
                    continue
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            _quick_filter_focus_relays.pop(key, None)
        try:
            relay = _QuickFilterFocusRelay(editor, surface)
            editor.installEventFilter(relay)
            def destroyed(_object=None, relay_key=key):
                _quick_filter_focus_relays.pop(relay_key, None)

            relay.destroyed_signal = editor.destroyed
            relay.destroyed_callback = destroyed
            relay.destroyed_connection = editor.destroyed.connect(destroyed)
            _quick_filter_focus_relays[key] = relay
            _set_quick_filter_focus(surface, editor.hasFocus())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue


def _restore_quick_filter_focus():
    restored_surfaces = set()
    for key, relay in list(_quick_filter_focus_relays.items()):
        try:
            relay.editor.removeEventFilter(relay)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        _disconnect_signal(
            relay.destroyed_signal,
            relay.destroyed_callback,
            relay.destroyed_connection,
        )
        try:
            surface_key = qobject_key(relay.surface)
            if surface_key in restored_surfaces:
                continue
            restored_surfaces.add(surface_key)
            original = relay.surface.property(_QUICK_FILTER_ORIGINAL_FOCUS_PROPERTY)
            relay.surface.setProperty(
                _QUICK_FILTER_FOCUS_PROPERTY,
                None if original == _QUICK_FILTER_PROPERTY_UNSET else original,
            )
            relay.surface.setProperty(_QUICK_FILTER_ORIGINAL_FOCUS_PROPERTY, None)
            _repolish(relay.surface)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        finally:
            _quick_filter_focus_relays.pop(key, None)
            try:
                relay.deleteLater()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass

    # A relay can disappear first when IDA destroys its editor. Restore any
    # surviving surface marker discovered at this lifecycle boundary.
    for surface in _targets():
        if not _is_builtin_quick_filter(surface):
            continue
        try:
            original = surface.property(_QUICK_FILTER_ORIGINAL_FOCUS_PROPERTY)
            if original is None:
                continue
            surface.setProperty(
                _QUICK_FILTER_FOCUS_PROPERTY,
                None if original == _QUICK_FILTER_PROPERTY_UNSET else original,
            )
            surface.setProperty(_QUICK_FILTER_ORIGINAL_FOCUS_PROPERTY, None)
            _repolish(surface)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass


def _targets(root=None):
    app = QApplication.instance()
    if app is None:
        return []
    try:
        if root is None:
            return list(app.allWidgets())
        return [root, *root.findChildren(QWidget)]
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return []


def _style_quick_filter(surface):
    if not _is_builtin_quick_filter(surface):
        return False
    _enable_quick_filter_surface(surface)
    _enable_quick_filter_buttons(surface)
    _enable_quick_filter_focus(surface)
    return True


def _refresh_quick_filter_host(host):
    """Style all direct quick-filter surfaces after one host-local event."""
    if not _enabled or not _is_quick_filter_host(host):
        return
    for widget in _targets(host):
        _style_quick_filter(widget)


def apply_panel_runtime():
    """Apply the narrow local-style repair at a lifecycle boundary."""
    global _enabled
    app = QApplication.instance()
    if app is None:
        return
    _enabled = True
    host_relay = _ensure_quick_filter_host_relay(app)
    for widget in _targets():
        if _is_quick_filter_host(widget):
            host_relay.watch(widget)
        if _is_output_cli_group(widget):
            _remember_and_style(widget)
        _apply_output_log_surface(widget)
        _style_quick_filter(widget)


def refresh_panel_runtime(root):
    """Inspect one visible panel tree without polling, paint, or resize hooks."""
    if not _enabled or root is None:
        return
    app = QApplication.instance()
    if app is None:
        return
    host_relay = _ensure_quick_filter_host_relay(app)
    ancestor_host = _quick_filter_host_ancestor(root)
    if ancestor_host is not None:
        host_relay.watch(ancestor_host)
        # The lifecycle root and quick filter are siblings in dirtree panels.
        # Style the already-constructed sibling immediately; the relay covers
        # any children that IDA adds after this callback returns.
        _refresh_quick_filter_host(ancestor_host)
    for widget in _targets(root):
        if _is_quick_filter_host(widget):
            host_relay.watch(widget)
        if _is_output_cli_group(widget):
            _remember_and_style(widget)
        _apply_output_log_surface(widget)
        if _style_quick_filter(widget):
            try:
                host_relay.watch(widget.parentWidget())
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass


def restore_panel_runtime():
    """Restore every surviving target's exact pre-theme local stylesheet."""
    global _enabled, _quick_filter_host_relay
    _enabled = False
    host_relay = _quick_filter_host_relay
    _quick_filter_host_relay = None
    if host_relay is not None:
        try:
            host_relay.deactivate()
            host_relay.deleteLater()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    _restore_quick_filter_focus()
    _restore_quick_filter_buttons()
    for widget in _targets():
        _restore_output_log_surface(widget)
        if _is_output_cli_group(widget):
            try:
                original = widget.property(_ORIGINAL_STYLE_PROPERTY)
                if original is None:
                    if widget.styleSheet().strip() != _CLI_GROUP_STYLE:
                        continue
                    original = _HOST_CLI_GROUP_STYLE
                widget.setStyleSheet(original)
                widget.setProperty(_ORIGINAL_STYLE_PROPERTY, None)
                widget.updateGeometry()
                widget.update()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if _is_builtin_quick_filter(widget):
            try:
                original = widget.property(_QUICK_FILTER_STYLED_PROPERTY)
                if original is None:
                    continue
                widget.setAttribute(
                    _styled_background_attribute(), bool(original)
                )
                originals = [
                    widget.property(name)
                    for name in _QUICK_FILTER_MARGIN_PROPERTIES
                ]
                if all(value is not None for value in originals):
                    widget.setContentsMargins(
                        *[int(value) for value in originals]
                    )
                    widget.updateGeometry()
                for name in _QUICK_FILTER_MARGIN_PROPERTIES:
                    widget.setProperty(name, None)
                widget.setProperty(_QUICK_FILTER_STYLED_PROPERTY, None)
                widget.update()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass


def panel_runtime_diagnostics():
    live = 0
    quick_filters = 0
    output_logs = 0
    for widget in _targets():
        if _is_output_cli_group(widget):
            try:
                if widget.styleSheet().strip() == _CLI_GROUP_STYLE:
                    live += 1
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if _is_builtin_quick_filter(widget):
            try:
                if widget.testAttribute(_styled_background_attribute()):
                    quick_filters += 1
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if _is_output_log(widget):
            try:
                if str(widget.property(_OUTPUT_LOG_MARK_PROPERTY) or "") == "v1":
                    output_logs += 1
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
    host_relay = _quick_filter_host_relay
    return {
        "enabled": bool(_enabled),
        "cli_group_count": live,
        "quick_filter_surface_count": quick_filters,
        "quick_filter_focus_relay_count": len(_quick_filter_focus_relays),
        "quick_filter_button_state_count": len(_quick_filter_button_states),
        "quick_filter_host_relay_count": 1 if host_relay is not None else 0,
        "quick_filter_host_watch_count": (
            host_relay.host_count if host_relay is not None else 0
        ),
        "quick_filter_host_pending_count": (
            host_relay.pending_count if host_relay is not None else 0
        ),
        "output_log_count": output_logs,
        "output_log_apply_count": int(_output_log_count),
    }
