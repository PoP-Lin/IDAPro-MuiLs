# -*- coding: utf-8 -*-
"""Rounded selection edges for IDA's built-in row-oriented panels.

Functions, Names, and Strings paint a selected row once per model column.
Applying a radius to the item sub-control therefore produces disconnected
pills.  This runtime leaves the native, continuous selection fill in place
and masks only the four outer corners after the viewport has painted.

Each paint filter is attached to one qualifying built-in viewport.  A second
relay is attached only to its persistent panel host and coalesces ChildAdded
or Show into a zero-delay, one-shot rescan when IDA rebuilds a native view.
Neither filter is application-wide, and no recurring timer or resize scan is
used.  Widgets carrying the plugin-panel marker remain excluded.  The real
viewport remains the mouse/scroll target.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # IDA 9.3 (Qt 6)
    from PySide6.QtCore import QEvent, QObject, QRectF, QTimer, Qt
    from PySide6.QtGui import (
        QBrush,
        QColor,
        QPaintEvent,
        QPainter,
        QPainterPath,
        QPalette,
        QPen,
    )
    from PySide6.QtWidgets import QApplication, QAbstractItemView, QTreeView, QWidget
except ImportError:  # pragma: no cover - Qt 5 IDA builds
    try:
        from PyQt5.QtCore import QEvent, QObject, QRectF, QTimer, Qt
        from PyQt5.QtGui import (
            QBrush,
            QColor,
            QPaintEvent,
            QPainter,
            QPainterPath,
            QPalette,
            QPen,
        )
        from PyQt5.QtWidgets import QApplication, QAbstractItemView, QTreeView, QWidget
    except ImportError:  # pragma: no cover - static tooling outside IDAPython
        QApplication = None  # type: ignore[assignment]
        QAbstractItemView = QTreeView = QWidget = object  # type: ignore[assignment,misc]
        QEvent = QObject = QRectF = QTimer = Qt = None  # type: ignore[assignment]
        QBrush = QColor = QPaintEvent = QPainter = None  # type: ignore[assignment]
        QPainterPath = QPalette = QPen = None  # type: ignore[assignment]

from .qt_compat import qobject_key, same_qobject


_FUNCTIONS_CLASS = "functions_dirtree_widget_t"
_NAMES_CLASS = "names_dirtree_widget_t"
_STRINGS_CLASSES = ("tchooser_table_widget_t", "chooser_table_widget_t")
_DIRTREE_HOST_CLASS = "standalone_dirtree_widget_host_t"
_CHOOSER_HOST_CLASS = "chooser_widget_t"
_SPLITTER_CLASS = "QSplitter"
_STRINGS_SPLITTER_NAME = "strings_splitter"
_PLUGIN_MARKER = "modernUiPluginPanel"
_TARGET_NAMES = ("functions", "names", "strings")
_LOCAL_STYLE_BEGIN = "/* IDA Modern UI native selection begin */"
_LOCAL_STYLE_END = "/* IDA Modern UI native selection end */"
_NAMES_HIGHLIGHT_COLORS = {
    "highlight_bg_default": "#0F141B",
    "highlight_bg_selected": "#31405A",
}
_NAMES_LOCAL_STYLE = """
QTreeView {
    show-decoration-selected: 1;
    selection-background-color: #31405A;
    selection-color: #F0F4FA;
    qproperty-highlight_bg_default: #0F141B;
    qproperty-highlight_bg_selected: #31405A;
}
QTreeView::item:selected {
    background: #31405A;
    color: #F0F4FA;
    border-radius: 0;
}
QTreeView::item:selected:!active {
    background: #31405A;
    color: #D8E0EA;
}
""".strip()
_PAINT_EVENT = getattr(getattr(QEvent, "Type", QEvent), "Paint", getattr(QEvent, "Paint", None)) if QEvent else None
_CHILD_ADDED_EVENT = (
    getattr(getattr(QEvent, "Type", QEvent), "ChildAdded", getattr(QEvent, "ChildAdded", None))
    if QEvent
    else None
)
_RESIZE_EVENT = getattr(getattr(QEvent, "Type", QEvent), "Resize", getattr(QEvent, "Resize", None)) if QEvent else None
_SHOW_EVENT = getattr(getattr(QEvent, "Type", QEvent), "Show", getattr(QEvent, "Show", None)) if QEvent else None
_STYLE_EVENT = getattr(getattr(QEvent, "Type", QEvent), "StyleChange", getattr(QEvent, "StyleChange", None)) if QEvent else None
_PALETTE_EVENT = getattr(getattr(QEvent, "Type", QEvent), "PaletteChange", getattr(QEvent, "PaletteChange", None)) if QEvent else None
_NO_PEN = getattr(getattr(Qt, "PenStyle", Qt), "NoPen", getattr(Qt, "NoPen", None)) if Qt else None
_NO_BRUSH = getattr(getattr(Qt, "BrushStyle", Qt), "NoBrush", getattr(Qt, "NoBrush", None)) if Qt else None
_ODD_EVEN = getattr(getattr(Qt, "FillRule", Qt), "OddEvenFill", getattr(Qt, "OddEvenFill", None)) if Qt else None
_ANTIALIASING = getattr(getattr(QPainter, "RenderHint", QPainter), "Antialiasing", getattr(QPainter, "Antialiasing", None)) if QPainter else None

_RADIUS = 5.0
_BACKGROUND = "#111318"
_SELECTION_EDGE = "#50627A"
# IDA's private dirtree starts its native selected brush at the first cell's
# visual rectangle, leaving the viewport-side decoration gutter unfilled.
# Post-paint fills only the area before that rectangle; icons and labels begin
# inside the rectangle and therefore remain untouched.


@dataclass(frozen=True)
class _PaletteSnapshot:
    brushes: Dict[Tuple[Any, Any], Any]
    resolve_mask: int
    owned_mask: int


def _class_chain(widget: Any) -> Tuple[str, ...]:
    names: List[str] = []
    try:
        meta = widget.metaObject()
        while meta is not None:
            name = meta.className()
            if name:
                names.append(str(name))
            meta = meta.superClass()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return tuple(names)


def _inherits(widget: Any, class_name: str) -> bool:
    return class_name in _class_chain(widget)


def _ancestors(widget: Any) -> Iterable[Any]:
    current = widget
    seen = set()
    while current is not None:
        if not _is_valid_qobject(current):
            break
        key = qobject_key(current)
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


def _own_identity(widget: Any) -> str:
    """Return a stable English IDA panel identity when one is present."""

    for getter_name in ("objectName", "windowTitle", "accessibleName"):
        try:
            getter = getattr(widget, getter_name, None)
            value = str(getter() or "").strip().casefold() if callable(getter) else ""
            if value in _TARGET_NAMES:
                return value
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
    return ""


def _own_object_name(widget: Any) -> str:
    try:
        return str(widget.objectName() or "").strip().casefold()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return ""


def _has_identity(widget: Any, identity: str) -> bool:
    return any(_own_identity(ancestor) == identity for ancestor in _ancestors(widget))


def _target_kind(widget: Any) -> Optional[str]:
    if widget is None:
        return None
    if _is_plugin_panel(widget):
        return None
    if _inherits(widget, _FUNCTIONS_CLASS):
        kind = "functions"
    elif _inherits(widget, _NAMES_CLASS):
        kind = "names"
    elif any(_inherits(widget, name) for name in _STRINGS_CLASSES) and _has_identity(
        widget, "strings"
    ):
        kind = "strings"
    else:
        return None
    try:
        return kind if callable(getattr(widget, "viewport")) else None
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _is_target_tree(widget: Any) -> bool:
    """Compatibility name retained for the now tree-and-table target test."""

    return _target_kind(widget) is not None


def _is_valid_qobject(value: Any) -> bool:
    """Reject deleted binding wrappers before comparing their C++ keys."""

    if value is None:
        return False
    try:
        import shiboken6

        return bool(shiboken6.isValid(value))
    except ImportError:
        pass
    except (AttributeError, TypeError):
        # A non-Shiboken QObject may be valid under PyQt; try sip below.
        pass
    except (RuntimeError, ValueError):
        return False
    try:  # PyQt5 ships sip both as a package module and a top-level module.
        try:
            from PyQt5 import sip
        except ImportError:
            import sip  # type: ignore[no-redef]

        return not bool(sip.isdeleted(value))
    except ImportError:
        pass
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    try:
        value.metaObject()
        return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _is_host_class(widget: Any) -> bool:
    return (
        widget is not None
        and (
            _inherits(widget, _DIRTREE_HOST_CLASS)
            or _inherits(widget, _CHOOSER_HOST_CLASS)
            or _inherits(widget, _SPLITTER_CLASS)
        )
        and not _is_plugin_panel(widget)
    )


def _target_host_kind(widget: Any) -> Optional[str]:
    """Classify persistent hosts without treating arbitrary containers as targets."""

    if not _is_host_class(widget):
        return None
    identity = _own_identity(widget)
    if _inherits(widget, _DIRTREE_HOST_CLASS) and identity in {"functions", "names"}:
        return identity
    if _inherits(widget, _CHOOSER_HOST_CLASS) and identity == "strings":
        return identity
    if (
        _inherits(widget, _SPLITTER_CLASS)
        and _own_object_name(widget) == _STRINGS_SPLITTER_NAME
        and _has_identity(widget, "strings")
    ):
        return "strings"
    return None


def _is_functions_host(widget: Any) -> bool:
    return _target_host_kind(widget) == "functions"


def _target_host_for_tree(tree: Any) -> Any:
    """Return the nearest matching native panel host."""

    target_kind = _target_kind(tree)
    if target_kind is None:
        return None
    try:
        current = tree.parentWidget()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    seen = set()
    while current is not None:
        key = qobject_key(current)
        if key in seen:
            break
        seen.add(key)
        host_kind = _target_host_kind(current)
        if host_kind is not None:
            return current if host_kind == target_kind else None
        try:
            current = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            break
    return None


def _with_local_selection_style(widget: Any, kind: Optional[str]) -> bool:
    """Make Names' native decoration strip join its selected text cells."""

    if kind != "names":
        return False
    try:
        current = str(widget.styleSheet() or "")
        if _LOCAL_STYLE_BEGIN in current:
            return True
        block = f"{_LOCAL_STYLE_BEGIN}\n{_NAMES_LOCAL_STYLE}\n{_LOCAL_STYLE_END}"
        widget.setStyleSheet(f"{current.rstrip()}\n{block}\n" if current else f"{block}\n")
        return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _without_local_selection_style(stylesheet: Any) -> str:
    value = str(stylesheet or "")
    while True:
        start = value.find(_LOCAL_STYLE_BEGIN)
        if start < 0:
            break
        end = value.find(_LOCAL_STYLE_END, start + len(_LOCAL_STYLE_BEGIN))
        if end < 0:
            break
        value = value[:start] + value[end + len(_LOCAL_STYLE_END) :]
    return value.rstrip()


def _highlight_property_snapshot(widget: Any) -> Dict[str, Any]:
    """Copy private dirtree colours before the local qproperty override."""

    snapshot: Dict[str, Any] = {}
    for name in ("highlight_bg_default", "highlight_bg_selected"):
        try:
            value = widget.property(name)
            if value is not None:
                snapshot[name] = QColor(value) if isinstance(value, QColor) else value
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
    return snapshot


def _apply_names_highlight_properties(
    widget: Any, kind: Optional[str], original: Optional[Dict[str, Any]]
) -> None:
    """Set Names' exported colours directly; qproperty QSS is binding-dependent."""

    if kind != "names" or not original:
        return
    changed = False
    for name, color in _NAMES_HIGHLIGHT_COLORS.items():
        # Avoid creating dynamic properties on IDA builds that do not export
        # the corresponding native dirtree property.
        if name not in original:
            continue
        try:
            changed = bool(widget.setProperty(name, QColor(color))) or changed
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
    if changed:
        try:
            widget.update()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass


def _selection_palette_roles() -> Tuple[Tuple[Any, Any], ...]:
    """Return every group/role pair owned by the Names palette bridge."""

    if QPalette is None:
        return ()
    groups = getattr(QPalette, "ColorGroup", QPalette)
    roles = getattr(QPalette, "ColorRole", QPalette)
    try:
        color_groups = (
            getattr(groups, "Active"),
            getattr(groups, "Disabled"),
            getattr(groups, "Inactive"),
        )
        color_roles = (
            getattr(roles, "Highlight"),
            getattr(roles, "HighlightedText"),
        )
    except AttributeError:
        return ()
    return tuple((group, role) for group in color_groups for role in color_roles)


def _palette_resolve_mask(palette: Any) -> Optional[int]:
    """Read the explicit-role mask through the Qt 6 or Qt 5 binding API."""

    try:
        getter = getattr(palette, "resolveMask", None)
        if callable(getter):
            return int(getter())
        resolver = getattr(palette, "resolve", None)
        if callable(resolver):
            return int(resolver())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return None


def _set_palette_resolve_mask(palette: Any, mask: int) -> bool:
    """Set and verify the explicit-role mask without touching a live widget."""

    try:
        setter = getattr(palette, "setResolveMask", None)
        if callable(setter):
            setter(int(mask))
        else:
            resolver = getattr(palette, "resolve", None)
            if not callable(resolver):
                return False
            resolver(int(mask))
        return _palette_resolve_mask(palette) == int(mask)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _selection_palette_owned_mask(palette: Any) -> Optional[int]:
    """Probe the binding's role-bit layout instead of hard-coding Qt internals."""

    pairs = _selection_palette_roles()
    if len(pairs) != 6:
        return None
    owned_mask = 0
    try:
        for group, role in pairs:
            probe = QPalette(palette)
            if not _set_palette_resolve_mask(probe, 0):
                return None
            probe.setBrush(group, role, QBrush(palette.brush(group, role)))
            role_mask = _palette_resolve_mask(probe)
            if role_mask is None or role_mask == 0:
                return None
            owned_mask |= role_mask
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    return owned_mask or None


def _names_palette_snapshot(
    widget: Any, kind: Optional[str]
) -> Optional[_PaletteSnapshot]:
    """Snapshot only the native selection roles that this runtime owns."""

    if kind != "names" or QPalette is None or QBrush is None:
        return None
    try:
        palette = QPalette(widget.palette())
        resolve_mask = _palette_resolve_mask(palette)
        owned_mask = _selection_palette_owned_mask(palette)
        if resolve_mask is None or owned_mask is None:
            return None
        brushes = {
            pair: QBrush(palette.brush(*pair)) for pair in _selection_palette_roles()
        }
        if len(brushes) != 6:
            return None
        return _PaletteSnapshot(brushes, resolve_mask, owned_mask)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _apply_names_selection_palette(
    widget: Any,
    kind: Optional[str],
    snapshot: Optional[_PaletteSnapshot],
) -> None:
    """Keep native delegates and the painted decoration gutter in sync."""

    if kind != "names" or QPalette is None or snapshot is None:
        return
    try:
        palette = QPalette(widget.palette())
        current_mask = _palette_resolve_mask(palette)
        if current_mask is None:
            return
        roles = getattr(QPalette, "ColorRole", QPalette)
        highlight = getattr(roles, "Highlight")
        highlighted_text = getattr(roles, "HighlightedText")
        for group, role in snapshot.brushes:
            if role == highlight:
                color = "#31405A"
            elif role == highlighted_text:
                color = "#F0F4FA"
            else:
                return
            palette.setColor(group, role, QColor(color))
        if not _set_palette_resolve_mask(
            palette, current_mask | snapshot.owned_mask
        ):
            return
        widget.setPalette(palette)
        widget.update()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def _restore_names_selection_palette(
    widget: Any,
    snapshot: Optional[_PaletteSnapshot],
    current_palette: Any = None,
) -> None:
    """Restore owned selection roles while preserving every unrelated change."""

    if QPalette is None or snapshot is None:
        return
    try:
        palette = QPalette(
            current_palette if current_palette is not None else widget.palette()
        )
        current_mask = _palette_resolve_mask(palette)
        if current_mask is None:
            return
        for pair, brush in snapshot.brushes.items():
            palette.setBrush(*pair, QBrush(brush))
        restored_mask = (current_mask & ~snapshot.owned_mask) | (
            snapshot.resolve_mask & snapshot.owned_mask
        )
        if not _set_palette_resolve_mask(palette, restored_mask):
            return
        widget.setPalette(palette)
        widget.update()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def _color_for(viewport: Any) -> QColor:
    try:
        palette = viewport.palette()
        role_holder = getattr(QPalette, "ColorRole", QPalette)
        role = getattr(role_holder, "Base", getattr(QPalette, "Base", None))
        color = palette.color(role)
        if color.isValid() and color.alpha() > 0:
            # Avoid a white/black seam when a platform palette has not yet
            # inherited IDA's dark role during startup.
            if color.name().upper() not in {"#000000", "#FFFFFF"}:
                return QColor(color)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return QColor(_BACKGROUND)


def _selected_color(tree: Any, viewport: Any) -> QColor:
    """Read IDA's private selected-fill property with a palette fallback."""

    # ``functions_dirtree_widget_t`` exposes these as real Qt properties,
    # although the generated PySide wrapper does not provide accessor methods.
    for name in ("highlight_bg_selected", "highlight-bg-selected"):
        try:
            value = tree.property(name)
            if isinstance(value, QColor) and value.isValid() and value.alpha() > 0:
                return QColor(value)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
    try:
        palette = viewport.palette()
        role_holder = getattr(QPalette, "ColorRole", QPalette)
        role = getattr(role_holder, "Highlight", getattr(QPalette, "Highlight", None))
        value = palette.color(role)
        if value.isValid() and value.alpha() > 0:
            # IDA's default Qt highlight is bright blue; only use it when a
            # custom property was not installed and keep the fixture readable.
            return QColor(value)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return QColor("#31405A")


def _decoration_fill_right(tree: Any, row_left: int, anchor: Any) -> float:
    """Return the first cell boundary that safely ends the dirtree gutter.

    Reading the anchor's visual rectangle keeps the boundary correct at
    different DPI settings and indentation depths.  Nothing at or beyond the
    boundary is repainted, so native icons and text remain intact.
    """

    try:
        content_rect = tree.visualRect(anchor)
        boundary = float(content_rect.left())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        boundary = float(row_left)
    return max(float(row_left), boundary)


def _parent_key(index: Any) -> Tuple[Any, ...]:
    """Build a cheap, stable key for a QModelIndex parent on Qt5/Qt6."""

    try:
        internal = index.internalId()
        return ("id", int(internal), int(index.parent().row()), int(index.parent().column()))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        try:
            parent = index.parent()
            return ("rc", int(parent.row()), int(parent.column()), bool(parent.isValid()))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return ("root",)


def _selected_row_rects(tree: Any, viewport: Any, include_anchor: bool = False) -> List[Any]:
    """Return one viewport rectangle per selected model row.

    ``selectedRows(0)`` is sufficient for the usual row-selection mode, while
    the fallback to ``selectedIndexes`` also handles IDA builds that expose a
    cell-selection mode.  Every visible column is unioned so a radius is
    applied to the whole row rather than to individual cells.
    """

    try:
        model = tree.model()
        selection = tree.selectionModel()
        if model is None or selection is None:
            return []
        indexes = list(selection.selectedRows(0))
        if not indexes:
            indexes = list(selection.selectedIndexes())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return []
    if not indexes:
        return []

    grouped: Dict[Tuple[int, Tuple[Any, ...]], Any] = {}
    for index in indexes:
        try:
            if not index.isValid():
                continue
            grouped.setdefault((int(index.row()), _parent_key(index)), index)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue

    result: List[Any] = []
    try:
        viewport_rect = viewport.rect()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return result
    for (row, _parent), anchor in grouped.items():
        try:
            parent = anchor.parent()
            column_count = max(1, int(model.columnCount(parent)))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            column_count = 1
            parent = None
        left: Optional[int] = None
        top: Optional[int] = None
        right: Optional[int] = None
        bottom: Optional[int] = None
        for column in range(column_count):
            try:
                index = model.index(row, column, parent)
                rect = tree.visualRect(index)
                if rect is None or not rect.isValid() or not rect.intersects(viewport_rect):
                    continue
                l = max(int(rect.left()), int(viewport_rect.left()))
                t = max(int(rect.top()), int(viewport_rect.top()))
                r = min(int(rect.right()) + 1, int(viewport_rect.right()) + 1)
                b = min(int(rect.bottom()) + 1, int(viewport_rect.bottom()) + 1)
                if r <= l or b <= t:
                    continue
                left = l if left is None else min(left, l)
                top = t if top is None else min(top, t)
                right = r if right is None else max(right, r)
                bottom = b if bottom is None else max(bottom, b)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        if left is None or top is None or right is None or bottom is None:
            continue
        # ``visualRect()`` for a tree's first model column starts after the
        # indentation/decoration gutter (usually x=20).  IDA nevertheless
        # paints the selected decoration strip from the viewport edge.  Make
        # that strip part of the one geometry we round, rather than leaving a
        # second square block beside the rounded text cell.  The right edge is
        # likewise extended to the visible content edge; scroll-bar hit areas
        # live outside this viewport and are unaffected.
        left = int(viewport_rect.left())
        right = max(int(right), int(viewport_rect.right()) + 1)
        if include_anchor:
            result.append((left, top, right, bottom, anchor))
        else:
            result.append((left, top, right, bottom))
    return result


class _SelectionPaintFilter(QObject):
    """Paint the native viewport once, then mask only selected row corners."""

    def __init__(self, tree: Any, viewport: Any, runtime: "_SelectionRuntime") -> None:
        super().__init__(runtime)
        self._tree = tree
        self._viewport = viewport
        self._runtime = runtime
        self._painting = False

    def release(self) -> None:
        """Drop wrappers immediately; deleteLater only owns the QObject shell."""

        self._tree = None
        self._viewport = None

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - Qt API
        if not self._runtime.enabled or not same_qobject(watched, self._viewport):
            return False
        try:
            event_type = event.type()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        if event_type == _PAINT_EVENT:
            return self._paint_once(watched)
        if event_type in {_RESIZE_EVENT, _SHOW_EVENT, _STYLE_EVENT, _PALETTE_EVENT}:
            try:
                watched.update()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        return False

    def _paint_once(self, viewport: Any) -> bool:
        if self._painting or QPainter is None or QPaintEvent is None:
            return False
        app = QApplication.instance() if QApplication is not None else None
        if app is None:
            return False
        try:
            rect = viewport.rect()
            if rect.width() <= 2 or rect.height() <= 2:
                return False
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        self._painting = True
        try:
            # Dispatch native QTreeView painting exactly once.  The guard
            # prevents this synthetic event from entering the filter again.
            app.sendEvent(viewport, QPaintEvent(rect))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        finally:
            self._painting = False
        try:
            self._runtime._draw(viewport, self._tree)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            # Native content is already painted; cosmetic failures must not
            # blank the Functions view.
            pass
        return True


class _SelectionHostRelay(QObject):
    """Relay only low-volume lifecycle events from one native panel host."""

    def __init__(self, runtime: "_SelectionRuntime", host_key: Any) -> None:
        super().__init__(runtime)
        self._runtime = runtime
        self._host_key = host_key

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - Qt API
        runtime = self._runtime
        if runtime.enabled:
            try:
                event_type = event.type()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return False
            if event_type in {_CHILD_ADDED_EVENT, _SHOW_EVENT}:
                runtime._queue_host_scan(self._host_key, watched)
        return False


@dataclass
class _SelectionEntry:
    tree: Any
    viewport: Any
    filter: _SelectionPaintFilter
    connections: List[Tuple[Any, Any, Any]]
    destroyed_connection: Optional[Tuple[Any, Any, Any]] = None
    token: Any = None
    kind: str = ""
    local_style: bool = False
    highlight_properties: Optional[Dict[str, Any]] = None
    palette_snapshot: Optional[_PaletteSnapshot] = None
    viewport_palette_snapshot: Optional[_PaletteSnapshot] = None


@dataclass
class _SelectionHostEntry:
    host: Any
    relay: _SelectionHostRelay
    token: Any
    destroyed_connection: Optional[Tuple[Any, Any, Any]] = None
    pending: bool = False
    kind: str = ""


class _SelectionRuntime(QObject):
    def __init__(self) -> None:
        if QObject is not None:
            super().__init__()
        self.enabled = False
        self._entries: Dict[Any, _SelectionEntry] = {}
        self._hosts: Dict[Any, _SelectionHostEntry] = {}
        self._scan_count = 0
        self._attach_count = 0
        self._relay_scan_count = 0

    def apply(self, root: Any = None) -> None:
        if QApplication is None or QWidget is object:
            return
        self.enabled = True
        self._scan_count += 1
        for widget in self._iter_widgets(root):
            if _target_host_kind(widget) is not None:
                self._register_host(widget)
            if _is_target_tree(widget):
                host = _target_host_for_tree(widget)
                if host is not None:
                    self._register_host(host)
                self._attach(widget)
        self._prune()

    def refresh(self, root: Any = None) -> None:
        if self.enabled:
            self.apply(root)

    def restore(self) -> None:
        self.enabled = False
        for key, entry in tuple(self._entries.items()):
            self._detach(key, entry)
        for key, entry in tuple(self._hosts.items()):
            self._unregister_host(key, entry)

    def diagnostics(self) -> dict:
        target_counts = {
            kind: sum(1 for entry in self._entries.values() if entry.kind == kind)
            for kind in _TARGET_NAMES
        }
        host_counts = {
            kind: sum(1 for entry in self._hosts.values() if entry.kind == kind)
            for kind in _TARGET_NAMES
        }
        return {
            "enabled": bool(self.enabled),
            # Preserve the original Functions-specific fields for existing
            # diagnostics consumers while exposing the expanded inventory.
            "functions_count": target_counts["functions"],
            "names_count": target_counts["names"],
            "strings_count": target_counts["strings"],
            "target_count": len(self._entries),
            "host_count": host_counts["functions"],
            "target_host_count": len(self._hosts),
            "pending_host_count": sum(1 for entry in self._hosts.values() if entry.pending),
            "scan_count": int(self._scan_count),
            "attach_count": int(self._attach_count),
            "relay_scan_count": int(self._relay_scan_count),
        }

    @staticmethod
    def _iter_widgets(root: Any = None) -> Iterable[Any]:
        roots = []
        if root is not None:
            roots.append(root)
        else:
            try:
                roots.extend(QApplication.topLevelWidgets())
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return ()
        seen = set()
        for candidate in roots:
            if not _is_valid_qobject(candidate):
                continue
            widgets = [candidate]
            try:
                widgets.extend(candidate.findChildren(QWidget))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            for widget in widgets:
                # shiboken6.getCppPointer() can terminate the interpreter for
                # a wrapper whose C++ object was already deleted. Validate
                # before qobject_key(), including explicitly supplied roots.
                if not _is_valid_qobject(widget):
                    continue
                key = qobject_key(widget)
                if key in seen:
                    continue
                seen.add(key)
                yield widget

    def _register_host(self, host: Any) -> None:
        """Install one lifecycle-only relay on a persistent built-in host."""

        kind = _target_host_kind(host) if _is_valid_qobject(host) else None
        if kind is None:
            return
        key = qobject_key(host)
        current = self._hosts.get(key)
        if current is not None:
            if _is_valid_qobject(current.host) and same_qobject(current.host, host):
                current.kind = kind
                return
            self._unregister_host(key, current)

        token = object()
        relay = _SelectionHostRelay(self, key)
        entry = _SelectionHostEntry(host, relay, token, kind=kind)
        try:
            host.installEventFilter(relay)

            def destroyed(_object: Any = None, host_key: Any = key, marker: Any = token) -> None:
                self._host_destroyed(host_key, marker)

            source = host.destroyed
            handle = source.connect(destroyed)
            entry.destroyed_connection = (source, destroyed, handle)
            self._hosts[key] = entry
        except (AttributeError, RuntimeError, TypeError, ValueError):
            try:
                host.removeEventFilter(relay)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            try:
                relay.deleteLater()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            return
        self._scan_host(key, token)

    def _queue_host_scan(self, host_key: Any, watched: Any) -> None:
        """Coalesce construction events until the native child is complete."""

        entry = self._hosts.get(host_key)
        if entry is None or entry.pending or QTimer is None:
            return
        if not _is_valid_qobject(watched):
            return
        # TWidgetToQtPythonWidget() can invalidate every Python wrapper for an
        # otherwise-live native panel. The C++ event filter remains installed
        # and supplies the replacement wrapper as ``watched``. Compare its key
        # without touching the stale wrapper, then rebind the cache in place.
        if qobject_key(watched) != host_key:
            return
        if not _is_valid_qobject(entry.host):
            entry.host = watched
        elif not same_qobject(entry.host, watched):
            return
        entry.pending = True
        token = entry.token

        def scan(marker: Any = token, key: Any = host_key) -> None:
            current = self._hosts.get(key)
            if current is None or current.token is not marker:
                return
            current.pending = False
            if self.enabled:
                self._scan_host(key, marker)

        try:
            QTimer.singleShot(0, scan)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            entry.pending = False

    def _scan_host(self, host_key: Any, token: Any) -> None:
        """Inspect one target host; never cross into another panel subtree."""

        entry = self._hosts.get(host_key)
        if entry is None or entry.token is not token:
            return
        host = entry.host
        if not _is_valid_qobject(host):
            self._unregister_host(host_key, entry, object_destroyed=True)
            return
        self._relay_scan_count += 1
        try:
            candidates = host.findChildren(QWidget)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            candidates = ()
        for candidate in candidates:
            if _target_host_kind(candidate) == entry.kind:
                self._register_host(candidate)
            if not _is_target_tree(candidate):
                continue
            if _target_kind(candidate) != entry.kind:
                continue
            owner = _target_host_for_tree(candidate)
            if owner is None or not _is_valid_qobject(owner):
                continue
            if same_qobject(owner, host):
                self._attach(candidate)

    def _host_destroyed(self, host_key: Any, token: Any) -> None:
        entry = self._hosts.get(host_key)
        if entry is None or entry.token is not token:
            return
        entry.destroyed_connection = None
        self._unregister_host(host_key, entry, object_destroyed=True)

    def _unregister_host(
        self,
        host_key: Any,
        entry: _SelectionHostEntry,
        object_destroyed: bool = False,
    ) -> None:
        if self._hosts.get(host_key) is entry:
            self._hosts.pop(host_key, None)
        host = entry.host
        entry.pending = False
        if not object_destroyed:
            try:
                host.removeEventFilter(entry.relay)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            self._disconnect_connection(entry.destroyed_connection)
        entry.destroyed_connection = None
        entry.host = None
        try:
            entry.relay.deleteLater()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    def _attach(self, tree: Any) -> None:
        kind = _target_kind(tree) if _is_valid_qobject(tree) else None
        if kind is None:
            return
        try:
            viewport = tree.viewport()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return
        if not _is_valid_qobject(viewport):
            return
        key = qobject_key(viewport)
        entry = self._entries.get(key)
        if entry is not None:
            old_valid = _is_valid_qobject(entry.tree) and _is_valid_qobject(entry.viewport)
            if (
                old_valid
                and same_qobject(entry.tree, tree)
                and same_qobject(entry.viewport, viewport)
            ):
                entry.kind = kind
                if not entry.local_style:
                    entry.highlight_properties = (
                        _highlight_property_snapshot(tree) if kind == "names" else None
                    )
                    if entry.palette_snapshot is None:
                        entry.palette_snapshot = _names_palette_snapshot(tree, kind)
                    if entry.viewport_palette_snapshot is None:
                        entry.viewport_palette_snapshot = _names_palette_snapshot(
                            viewport, kind
                        )
                    entry.local_style = _with_local_selection_style(tree, kind)
                _apply_names_highlight_properties(
                    tree, kind, entry.highlight_properties
                )
                _apply_names_selection_palette(tree, kind, entry.palette_snapshot)
                _apply_names_selection_palette(
                    viewport, kind, entry.viewport_palette_snapshot
                )
                self._connect_model_signals(entry)
                return
            self._detach(key, entry)
        paint_filter = None
        new_entry = None
        try:
            paint_filter = _SelectionPaintFilter(tree, viewport, self)
            viewport.installEventFilter(paint_filter)
            token = object()
            new_entry = _SelectionEntry(
                tree,
                viewport,
                paint_filter,
                [],
                token=token,
                kind=kind,
                highlight_properties=(
                    _highlight_property_snapshot(tree) if kind == "names" else None
                ),
                palette_snapshot=_names_palette_snapshot(tree, kind),
                viewport_palette_snapshot=_names_palette_snapshot(viewport, kind),
            )
            self._entries[key] = new_entry
            new_entry.local_style = _with_local_selection_style(tree, kind)
            _apply_names_highlight_properties(
                tree, kind, new_entry.highlight_properties
            )
            _apply_names_selection_palette(tree, kind, new_entry.palette_snapshot)
            _apply_names_selection_palette(
                viewport, kind, new_entry.viewport_palette_snapshot
            )

            def destroyed(
                _object: Any = None,
                viewport_key: Any = key,
                marker: Any = token,
            ) -> None:
                self._target_destroyed(viewport_key, marker)

            source = tree.destroyed
            handle = source.connect(destroyed)
            new_entry.destroyed_connection = (source, destroyed, handle)
            self._connect_model_signals(new_entry)
            self._attach_count += 1
        except (AttributeError, RuntimeError, TypeError, ValueError):
            if new_entry is not None:
                self._detach(key, new_entry)
            elif paint_filter is not None:
                try:
                    viewport.removeEventFilter(paint_filter)
                    paint_filter.release()
                    paint_filter.deleteLater()
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass

    def _target_destroyed(self, key: Any, token: Any) -> None:
        entry = self._entries.get(key)
        if entry is None or entry.token is not token:
            return
        entry.destroyed_connection = None
        self._detach(key, entry, object_destroyed=True)

    def _connect_model_signals(self, entry: _SelectionEntry) -> None:
        """Connect only low-volume model/selection signals (idempotent)."""

        # A marker on the entry records the model/selection object currently
        # connected; IDA can replace either when a chooser is rebuilt.
        try:
            model = entry.tree.model()
            selection = entry.tree.selectionModel()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return
        marker = getattr(entry, "_signal_sources", None)
        source_key = (qobject_key(model), qobject_key(selection))
        if marker == source_key:
            return
        # Disconnect old callbacks before replacing the source pair.
        self._disconnect_connections(entry)

        def invalidate(*_args: Any) -> None:
            try:
                entry.viewport.update()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass

        sources = []
        if selection is not None:
            sources.extend(
                getattr(selection, name, None)
                for name in ("selectionChanged", "currentChanged", "modelChanged")
            )
        if model is not None:
            sources.extend(
                getattr(model, name, None)
                for name in (
                    "modelReset",
                    "layoutChanged",
                    "rowsInserted",
                    "rowsRemoved",
                    "rowsMoved",
                    "dataChanged",
                )
            )
        for source in sources:
            if source is None or not hasattr(source, "connect"):
                continue
            try:
                handle = source.connect(invalidate)
                entry.connections.append((source, invalidate, handle))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        for bar_name in ("horizontalScrollBar", "verticalScrollBar"):
            try:
                bar = getattr(entry.tree, bar_name)()
                source = getattr(bar, "valueChanged", None)
                if source is not None and hasattr(source, "connect"):
                    handle = source.connect(invalidate)
                    entry.connections.append((source, invalidate, handle))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        setattr(entry, "_signal_sources", source_key)

    @staticmethod
    def _disconnect_connection(connection: Optional[Tuple[Any, Any, Any]]) -> None:
        """Release one signal link without warning after endpoint teardown."""

        if connection is None:
            return
        signal, callback, handle = connection
        if handle is not None and QObject is not None:
            try:
                # A QMetaObject.Connection remains safe to disconnect after
                # either endpoint has gone away. Qt simply returns false when
                # teardown already removed it.
                QObject.disconnect(handle)
                return
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
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

    @classmethod
    def _disconnect_connections(cls, entry: _SelectionEntry) -> None:
        """Release model links without re-disconnecting an auto-removed slot."""

        connections = tuple(entry.connections)
        entry.connections.clear()
        setattr(entry, "_signal_sources", None)
        for connection in connections:
            cls._disconnect_connection(connection)

    def _detach(
        self,
        key: Any,
        entry: _SelectionEntry,
        object_destroyed: bool = False,
    ) -> None:
        if entry is None:
            return
        if self._entries.get(key) is entry:
            self._entries.pop(key, None)
        try:
            entry.viewport.removeEventFilter(entry.filter)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        self._disconnect_connections(entry)
        if not object_destroyed:
            self._disconnect_connection(entry.destroyed_connection)
        entry.destroyed_connection = None
        current_palette = None
        current_viewport_palette = None
        if entry.palette_snapshot is not None and _is_valid_qobject(entry.tree):
            try:
                # Removing the local stylesheet makes Qt rebuild the widget
                # palette. Preserve the live, pre-removal values so unrelated
                # roles changed by another plugin remain intact.
                current_palette = QPalette(entry.tree.palette())
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if entry.viewport_palette_snapshot is not None and _is_valid_qobject(
            entry.viewport
        ):
            try:
                current_viewport_palette = QPalette(entry.viewport.palette())
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if entry.local_style and _is_valid_qobject(entry.tree):
            try:
                current_style = str(entry.tree.styleSheet() or "")
                restored_style = _without_local_selection_style(current_style)
                if current_style.rstrip() != restored_style:
                    entry.tree.setStyleSheet(restored_style)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if entry.highlight_properties and _is_valid_qobject(entry.tree):
            for name, value in entry.highlight_properties.items():
                try:
                    entry.tree.setProperty(name, value)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    continue
            try:
                entry.tree.update()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if entry.palette_snapshot is not None and _is_valid_qobject(entry.tree):
            _restore_names_selection_palette(
                entry.tree, entry.palette_snapshot, current_palette
            )
        if entry.viewport_palette_snapshot is not None and _is_valid_qobject(
            entry.viewport
        ):
            _restore_names_selection_palette(
                entry.viewport,
                entry.viewport_palette_snapshot,
                current_viewport_palette,
            )
        entry.local_style = False
        entry.highlight_properties = None
        entry.palette_snapshot = None
        entry.viewport_palette_snapshot = None
        try:
            entry.filter.release()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        try:
            entry.filter.deleteLater()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        entry.tree = None
        entry.viewport = None

    def _prune(self) -> None:
        stale = []
        for key, entry in tuple(self._entries.items()):
            try:
                if (
                    not _is_valid_qobject(entry.tree)
                    or not _is_valid_qobject(entry.viewport)
                    or not _is_target_tree(entry.tree)
                ):
                    stale.append((key, entry))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                stale.append((key, entry))
        for key, entry in stale:
            self._detach(key, entry)
        stale_hosts = []
        for key, entry in tuple(self._hosts.items()):
            # Wrapper invalidation is not C++ destruction in IDA. Keep the
            # native-installed relay until QObject.destroyed fires or a future
            # ChildAdded/Show event supplies a valid same-key wrapper.
            if _is_valid_qobject(entry.host) and _target_host_kind(entry.host) is None:
                stale_hosts.append((key, entry))
        for key, entry in stale_hosts:
            self._unregister_host(key, entry)

    @staticmethod
    def _draw(viewport: Any, tree: Any) -> None:
        if QPainter is None:
            return
        rects = _selected_row_rects(tree, viewport, include_anchor=True)
        if not rects:
            return
        painter = QPainter(viewport)
        try:
            if _ANTIALIASING is not None:
                painter.setRenderHint(_ANTIALIASING, True)
            if _NO_PEN is not None:
                painter.setPen(_NO_PEN)
            background = _color_for(viewport)
            selected = _selected_color(tree, viewport)
            needs_gutter_fill = _target_kind(tree) in {"functions", "names"}
            for record in rects:
                left, top, right, bottom, anchor = record
                row = QRectF(float(left), float(top), float(right - left), float(bottom - top))
                if row.width() <= 3.0 or row.height() <= 3.0:
                    continue
                # IDA leaves the decoration gutter before the first cell dark.
                # Fill exactly up to that cell boundary, then let the shared
                # corner mask shape the complete row.  The anchor's icon and
                # text live inside visualRect() and are never overpainted.
                if needs_gutter_fill:
                    fill_right = min(
                        float(right), _decoration_fill_right(tree, left, anchor)
                    )
                    if fill_right > float(left):
                        gutter = QRectF(
                            float(left),
                            float(top),
                            fill_right - float(left),
                            float(bottom - top),
                        )
                        painter.fillRect(gutter, selected)
                radius = min(_RADIUS, row.width() / 2.0, row.height() / 2.0)
                inner = row.adjusted(0.35, 0.35, -0.35, -0.35)
                outside = QPainterPath()
                outside.addRect(row)
                outside.addRoundedRect(inner, radius, radius)
                if _ODD_EVEN is not None:
                    outside.setFillRule(_ODD_EVEN)
                painter.fillPath(outside, background)

                # A very quiet outline improves the anti-aliased edge on dark
                # themes without turning the selection into a bright border.
                edge = QColor(_SELECTION_EDGE)
                edge.setAlpha(105)
                painter.setBrush(_NO_BRUSH if _NO_BRUSH is not None else background)
                painter.setPen(QPen(edge, 1.0))
                outline = inner.adjusted(0.5, 0.5, -0.5, -0.5)
                painter.drawRoundedRect(outline, max(1.0, radius - 0.5), max(1.0, radius - 0.5))
                if _NO_PEN is not None:
                    painter.setPen(_NO_PEN)
        finally:
            painter.end()


_RUNTIME = _SelectionRuntime() if QObject is not None else None


def apply_selection_runtime(root: Any = None) -> None:
    if _RUNTIME is not None:
        _RUNTIME.apply(root)


def refresh_selection_runtime(root: Any = None) -> None:
    if _RUNTIME is not None:
        _RUNTIME.refresh(root)


def restore_selection_runtime() -> None:
    if _RUNTIME is not None:
        _RUNTIME.restore()


def selection_runtime_diagnostics() -> dict:
    if _RUNTIME is None:
        return {
            "enabled": False,
            "functions_count": 0,
            "names_count": 0,
            "strings_count": 0,
            "target_count": 0,
            "host_count": 0,
            "target_host_count": 0,
            "pending_host_count": 0,
            "scan_count": 0,
            "attach_count": 0,
            "relay_scan_count": 0,
        }
    return _RUNTIME.diagnostics()


__all__ = [
    "apply_selection_runtime",
    "refresh_selection_runtime",
    "restore_selection_runtime",
    "selection_runtime_diagnostics",
]
