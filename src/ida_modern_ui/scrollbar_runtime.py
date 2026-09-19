# -*- coding: utf-8 -*-
"""Rounded scrollbar overlays for IDA's built-in views.

IDA 9.3 uses a custom Qt style for scrollbars.  Although the style sheet
accepts ``border-radius`` on ``QScrollBar::handle``, the native complex-control
paint path still emits a solid rectangle (Qt 6.6 exhibits the same behaviour).
This module keeps the native scrollbar as the hit-test/scrolling surface and
adds a tiny, mouse-transparent child that paints only the visual rail/thumb.

The overlay is deliberately scoped to IDA-owned view classes.  Plugin panels
are left on their own style sheet and no application-wide event filter or
timer is installed.  Geometry is refreshed only on scrollbar signals and the
small local event filter (resize/show/style/mouse events for that scrollbar).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple

try:  # IDA 9.3 (Qt 6)
    from PySide6.QtCore import QEvent, QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPalette
    from PySide6.QtWidgets import (
        QApplication,
        QScrollBar,
        QStyle,
        QStyleOptionSlider,
        QWidget,
    )
except ImportError:  # pragma: no cover - exercised on Qt 5 IDA builds
    try:
        from PyQt5.QtCore import QEvent, QRectF, Qt
        from PyQt5.QtGui import QColor, QPainter, QPalette
        from PyQt5.QtWidgets import (
            QApplication,
            QScrollBar,
            QStyle,
            QStyleOptionSlider,
            QWidget,
        )
    except ImportError:  # pragma: no cover - allows static tooling off-IDAPython
        QApplication = None  # type: ignore[assignment]
        QScrollBar = None  # type: ignore[assignment]
        QStyle = None  # type: ignore[assignment]
        QStyleOptionSlider = None  # type: ignore[assignment]
        QEvent = QRectF = Qt = QColor = QPainter = QPalette = None  # type: ignore[assignment]
        QWidget = object  # type: ignore[assignment,misc]


_TARGET_CLASSES = frozenset(
    {
        # Built-in chooser/tree cards.
        "TChooser",
        "chooser_widget_t",
        "tchooser_table_widget_t",
        "chooser_table_widget_t",
        "standalone_dirtree_widget_t",
        "base_dirtree_widget_t",
        "ida_dirtree_widget_t",
        "names_dirtree_widget_t",
        "functions_dirtree_widget_t",
        # Built-in Output/console and IDA views.
        "log_widget_t",
        "MainMsgList",
        "CustomIDAMemo",
        "IDAView",
        "EAView",
        "text_area_t",
        "viewer_t",
    }
)

_PLUGIN_MARKER = "modernUiPluginPanel"
_OVERLAY_MARKER = "modernUiRoundedScrollbarOverlay"
_DEFAULT_TRACK = "#0F141B"
_DEFAULT_RAIL = "#1B2028"
_DEFAULT_HANDLE = "#394351"
_HOVER_HANDLE = "#526072"
_PRESSED_HANDLE = "#60708A"
_DISABLED_HANDLE = "#2B333F"


def _enum(owner: Any, nested: str, name: str, default: Any = None) -> Any:
    """Resolve Qt5/Qt6 enum spellings without importing binding-specific code."""

    if owner is None:
        return default
    holder = getattr(owner, nested, owner)
    return getattr(holder, name, getattr(owner, name, default))


def _event_type(name: str) -> Any:
    return _enum(QEvent, "Type", name, getattr(QEvent, name, None) if QEvent else None)


def _qt_value(nested: str, name: str, legacy: Any = None) -> Any:
    """Resolve a Qt enum value on both scoped (Qt6) and flat (Qt5) bindings."""

    fallback_name = legacy or name
    fallback = getattr(Qt, fallback_name, None) if Qt is not None else None
    return _enum(Qt, nested, name, fallback)


def _qobject_key(value: Any) -> Tuple[str, int]:
    """Return a stable C++ identity for PySide/PyQt wrappers."""

    if value is None:
        return ("none", 0)
    try:
        import shiboken6

        # PySide 6.8 can access-violate instead of raising when getCppPointer()
        # receives a wrapper whose C++ QObject has already been destroyed.
        if not shiboken6.isValid(value):
            return ("python", id(value))
        pointer = shiboken6.getCppPointer(value)
        if pointer:
            return ("cpp", int(pointer[0]))
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass
    try:
        import sip

        return ("cpp", int(sip.unwrapinstance(value)))
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        return ("python", id(value))


def _class_chain(widget: Any) -> Tuple[str, ...]:
    """Read Qt meta-object class names for ``widget`` and its C++ bases."""

    result = []
    try:
        meta = widget.metaObject()
        while meta is not None:
            name = meta.className()
            if name:
                result.append(str(name))
            meta = meta.superClass()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return tuple(result)


def _ancestors(widget: Any) -> Iterable[Any]:
    current = widget
    seen = set()
    while current is not None:
        key = _qobject_key(current)
        if key in seen:
            break
        seen.add(key)
        yield current
        try:
            current = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            break


def _is_plugin_panel(widget: Any) -> bool:
    for ancestor in _ancestors(widget):
        try:
            if bool(ancestor.property(_PLUGIN_MARKER)):
                return True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
    return False


def _is_builtin_scrollbar(bar: Any) -> bool:
    """Return true only for a scrollbar hosted by IDA-owned view classes."""

    if QScrollBar is None or bar is None:
        return False
    try:
        if not isinstance(bar, QScrollBar) or _is_plugin_panel(bar):
            return False
    except (TypeError, RuntimeError):
        return False
    # Only inspect the nearest QAbstractScrollArea owner.  Header views have
    # their own hidden scrollbars; walking farther up to the outer chooser
    # would attach redundant overlays to all of those internal bars.
    for ancestor in _ancestors(bar):
        chain = _class_chain(ancestor)
        if "QAbstractScrollArea" not in chain:
            continue
        return any(name in _TARGET_CLASSES for name in chain)
    return False


def _background_for(bar: Any) -> str:
    """Use a stable card color; palette fallback keeps other IDA themes legible."""

    # Built-in cards use this color in modern_dark.qss.  Reading the palette
    # lets a future theme with a different window color avoid a bright seam.
    try:
        parent = bar.parentWidget()
        if parent is not None:
            palette = parent.palette()
            role = _enum(QPalette, "ColorRole", "Base", getattr(QPalette, "Base", None))
            color = palette.color(role)
            if color.isValid() and color.alpha() > 0:
                rgb = color.name().upper()
                if rgb not in {"#000000", "#FFFFFF"}:
                    return rgb
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return _DEFAULT_TRACK


def _subcontrol_rect(bar: Any) -> Any:
    """Resolve the current native slider rectangle for robust value mapping."""

    if QStyleOptionSlider is None or QStyle is None:
        return None
    try:
        option = QStyleOptionSlider()
        option.initFrom(bar)
        option.orientation = bar.orientation()
        option.minimum = int(bar.minimum())
        option.maximum = int(bar.maximum())
        option.sliderPosition = int(bar.sliderPosition())
        option.sliderValue = int(bar.sliderPosition())
        option.pageStep = int(bar.pageStep())
        option.singleStep = int(bar.singleStep())
        option.rect = bar.rect()
        cc = _enum(QStyle, "ComplexControl", "CC_ScrollBar")
        sc = _enum(QStyle, "SubControl", "SC_ScrollBarSlider")
        if cc is None or sc is None:
            return None
        rect = bar.style().subControlRect(cc, option, sc, bar)
        return rect if rect is not None and rect.isValid() else None
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


class _RoundedScrollbarOverlay(QWidget):
    """Mouse-transparent visual layer attached directly to one QScrollBar."""

    def __init__(self, bar: Any, track_color: str = _DEFAULT_TRACK):
        super().__init__(bar)
        self._bar = bar
        self._track_color = QColor(track_color)
        self._rail_color = QColor(_DEFAULT_RAIL)
        self._handle_color = QColor(_DEFAULT_HANDLE)
        self._hover_color = QColor(_HOVER_HANDLE)
        self._pressed_color = QColor(_PRESSED_HANDLE)
        self._disabled_color = QColor(_DISABLED_HANDLE)
        try:
            self.setObjectName(_OVERLAY_MARKER)
            self.setProperty(_OVERLAY_MARKER, True)
            transparent = _qt_value(
                "WidgetAttribute", "WA_TransparentForMouseEvents"
            )
            translucent = _qt_value("WidgetAttribute", "WA_TranslucentBackground")
            if transparent is not None:
                self.setAttribute(transparent, True)
            if translucent is not None:
                self.setAttribute(translucent, True)
            self.setAutoFillBackground(False)
            # Prevent broad application QSS (for example ``QWidget { ... }``)
            # from adding a second rectangular frame behind the antialiased
            # paint.  The overlay owns all of its pixels in paintEvent().
            self.setStyleSheet("background: transparent; border: 0;")
            no_focus = _qt_value("FocusPolicy", "NoFocus")
            if no_focus is not None:
                self.setFocusPolicy(no_focus)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        self._sync_geometry()
        self._connect_signals()
        try:
            bar.installEventFilter(self)
            bar.destroyed.connect(self._on_bar_destroyed)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        if getattr(bar, "isVisible", lambda: False)():
            self.show()
            self.raise_()
        else:
            self.hide()

    def _connect_signals(self) -> None:
        bar = self._bar
        for name in (
            "valueChanged",
            "rangeChanged",
            "sliderMoved",
            "sliderPressed",
            "sliderReleased",
        ):
            try:
                signal = getattr(bar, name)
                signal.connect(self._update_from_signal)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue

    def _update_from_signal(self, *_args: Any) -> None:
        try:
            self.update()
        except (AttributeError, RuntimeError, TypeError):
            pass

    def _on_bar_destroyed(self, *_args: Any) -> None:
        self._bar = None
        try:
            self.deleteLater()
        except (AttributeError, RuntimeError, TypeError):
            pass

    def _sync_geometry(self) -> None:
        bar = self._bar
        if bar is None:
            return
        try:
            self.setGeometry(bar.rect())
            if bar.isVisible():
                # ``QWidget`` wrappers can be recreated by IDA's embedded
                # Python binding between layout passes; always re-show after
                # a resize/show event instead of relying on wrapper identity.
                self.show()
            else:
                self.hide()
            self.raise_()
            self.update()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    def eventFilter(self, watched: Any, event: Any) -> bool:
        same_bar = False
        try:
            same_bar = self._bar is not None and _qobject_key(watched) == _qobject_key(self._bar)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        if same_bar:
            event_type = event.type()
            if event_type in {
                _event_type("Resize"),
                _event_type("Move"),
                _event_type("Show"),
                _event_type("ShowToParent"),
                _event_type("Hide"),
                _event_type("ParentChange"),
                _event_type("LayoutRequest"),
                _event_type("StyleChange"),
                _event_type("PaletteChange"),
                _event_type("EnabledChange"),
            }:
                self._sync_geometry()
            elif event_type in {
                _event_type("MouseMove"),
                _event_type("Enter"),
                _event_type("Leave"),
            }:
                self.update()
        try:
            return super().eventFilter(watched, event)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def paintEvent(self, _event: Any) -> None:  # noqa: N802 - Qt API
        bar = self._bar
        if bar is None or QPainter is None or QRectF is None:
            return
        try:
            if bar.maximum() <= bar.minimum():
                return
            rect = self.rect()
            if rect.width() <= 1 or rect.height() <= 1:
                return
            vertical = bar.orientation() == _qt_value("Orientation", "Vertical")
            painter = QPainter(self)
            antialias = _enum(
                QPainter,
                "RenderHint",
                "Antialiasing",
                getattr(QPainter, "Antialiasing", None) if QPainter else None,
            )
            no_pen = _qt_value("PenStyle", "NoPen")
            if antialias is not None:
                painter.setRenderHint(antialias, True)
            if no_pen is not None:
                painter.setPen(no_pen)
            # Mask the native rectangular handle while retaining the native
            # scrollbar's hit target and range behavior underneath.
            painter.setBrush(self._track_color)
            painter.drawRect(rect)

            if vertical:
                rail_width = max(4.0, min(8.0, float(rect.width()) - 2.0))
                rail = QRectF(
                    (rect.width() - rail_width) / 2.0,
                    1.0,
                    rail_width,
                    max(2.0, float(rect.height()) - 2.0),
                )
            else:
                rail_height = max(4.0, min(8.0, float(rect.height()) - 2.0))
                rail = QRectF(
                    1.0,
                    (rect.height() - rail_height) / 2.0,
                    max(2.0, float(rect.width()) - 2.0),
                    rail_height,
                )
            rail_radius = min(rail.width(), rail.height()) / 2.0
            painter.setBrush(self._rail_color)
            painter.drawRoundedRect(rail, rail_radius, rail_radius)

            native = _subcontrol_rect(bar)
            if native is None:
                painter.end()
                return
            if vertical:
                handle = QRectF(
                    rail.left(),
                    max(rail.top(), float(native.top()) + 1.0),
                    rail.width(),
                    max(4.0, min(rail.height(), float(native.height()) - 2.0)),
                )
            else:
                handle = QRectF(
                    max(rail.left(), float(native.left()) + 1.0),
                    rail.top(),
                    max(4.0, min(rail.width(), float(native.width()) - 2.0)),
                    rail.height(),
                )
            # Keep the rounded thumb within the rail even when the native style
            # reports a slider rect touching an arrow/page boundary.
            if vertical:
                handle.setBottom(min(handle.bottom(), rail.bottom()))
            else:
                handle.setRight(min(handle.right(), rail.right()))
            if not handle.isValid():
                painter.end()
                return

            try:
                pressed = bool(bar.isSliderDown())
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pressed = False
            if not bar.isEnabled():
                color = self._disabled_color
            elif pressed:
                color = self._pressed_color
            elif bar.underMouse():
                color = self._hover_color
            else:
                color = self._handle_color
            painter.setBrush(color)
            radius = min(handle.width(), handle.height()) / 2.0
            painter.drawRoundedRect(handle, radius, radius)
            painter.end()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            try:
                painter.end()  # type: ignore[name-defined]
            except (AttributeError, UnboundLocalError):
                pass


@dataclass
class _OverlayEntry:
    bar: Any
    overlay: _RoundedScrollbarOverlay


class _ScrollbarRuntime:
    def __init__(self) -> None:
        self._entries: Dict[Tuple[str, int], _OverlayEntry] = {}
        self._enabled = False
        self._scan_count = 0
        self._attach_count = 0

    def apply(self, root: Any = None) -> None:
        if QScrollBar is None or QApplication is None:
            return
        self._enabled = True
        self._scan_count += 1
        for bar in self._iter_scrollbars(root):
            if _is_builtin_scrollbar(bar):
                self._attach(bar)
        self._prune()

    def refresh(self, root: Any = None) -> None:
        if self._enabled:
            self.apply(root)

    def restore(self) -> None:
        self._enabled = False
        entries = list(self._entries.values())
        self._entries.clear()
        for entry in entries:
            self._detach_entry(entry)

    def diagnostics(self) -> dict:
        live = 0
        for entry in tuple(self._entries.values()):
            try:
                if entry.bar is not None and not entry.bar.isHidden():
                    live += 1
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        return {
            "enabled": bool(self._enabled),
            "overlay_count": len(self._entries),
            "visible_count": live,
            "scan_count": int(self._scan_count),
            "attach_count": int(self._attach_count),
        }

    @staticmethod
    def _iter_scrollbars(root: Any) -> Iterable[Any]:
        roots = []
        if root is not None:
            roots.append(root)
        else:
            try:
                roots.extend(QApplication.topLevelWidgets())
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return ()
        seen = set()
        for candidate_root in roots:
            try:
                candidates = [candidate_root, *candidate_root.findChildren(QScrollBar)]
            except (AttributeError, RuntimeError, TypeError, ValueError):
                candidates = [candidate_root]
            for bar in candidates:
                key = _qobject_key(bar)
                if key in seen:
                    continue
                seen.add(key)
                yield bar

    def _attach(self, bar: Any) -> None:
        key = _qobject_key(bar)
        entry = self._entries.get(key)
        if entry is not None:
            try:
                entry.overlay._sync_geometry()
                return
            except (AttributeError, RuntimeError, TypeError, ValueError):
                self._entries.pop(key, None)
        try:
            overlay = _RoundedScrollbarOverlay(bar, _background_for(bar))
            self._entries[key] = _OverlayEntry(bar, overlay)
            self._attach_count += 1
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

    def _prune(self) -> None:
        stale = []
        for key, entry in tuple(self._entries.items()):
            try:
                # A plugin can register/tag a panel after the initial scan.
                # Remove an existing overlay immediately rather than leaving
                # a core paint layer on a panel that now owns its styling.
                if (
                    entry.bar is None
                    or entry.overlay._bar is None
                    or not _is_builtin_scrollbar(entry.bar)
                ):
                    stale.append(key)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                stale.append(key)
        for key in stale:
            entry = self._entries.pop(key, None)
            if entry is not None:
                self._detach_entry(entry)

    @staticmethod
    def _detach_entry(entry: _OverlayEntry) -> None:
        bar = entry.bar
        overlay = entry.overlay
        try:
            bar.removeEventFilter(overlay)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        try:
            overlay.hide()
            overlay.deleteLater()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass


_RUNTIME = _ScrollbarRuntime()


def apply_scrollbar_runtime(root: Any = None) -> None:
    """Attach rounded overlays to built-in scrollbars (idempotent)."""

    _RUNTIME.apply(root)


def refresh_scrollbar_runtime(root: Any = None) -> None:
    """Refresh overlays for a newly visible IDA widget subtree."""

    _RUNTIME.refresh(root)


def restore_scrollbar_runtime() -> None:
    """Remove all overlays and local event filters."""

    _RUNTIME.restore()


def scrollbar_runtime_diagnostics() -> dict:
    return _RUNTIME.diagnostics()


__all__ = [
    "apply_scrollbar_runtime",
    "refresh_scrollbar_runtime",
    "restore_scrollbar_runtime",
    "scrollbar_runtime_diagnostics",
]
