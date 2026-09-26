# -*- coding: utf-8 -*-
"""Small, local paint overlays for IDA's navigation band.

``navband_t`` is an IDA custom-painted widget.  Its colour properties can be
set from QSS, but the native painter intentionally fills a square rectangle,
so a QSS ``border-radius`` does not clip the coloured segments.  This module
uses the same technique as IDA's ``paint_over_navbar.py`` example: a filter is
installed only on the navigation band, the native paint event is dispatched
once, and a cheap post-paint mask rounds/insets the visual rail.  The widget's
real geometry is left untouched, preserving navigation hit testing and plugin
compatibility.

The legend swatches are ordinary ``ui_label_t`` children.  They receive a
dynamic property so the stylesheet can round only the 15x15 colour chips,
without changing the adjacent text labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

try:  # IDA 9.3 (Qt 6)
    from PySide6.QtCore import QEvent, QObject, QRectF, Qt
    from PySide6.QtGui import QColor, QPaintEvent, QPainter, QPainterPath, QPalette, QPen
    from PySide6.QtWidgets import QApplication, QWidget
except ImportError:  # pragma: no cover - Qt 5 IDA builds
    try:
        from PyQt5.QtCore import QEvent, QObject, QRectF, Qt
        from PyQt5.QtGui import QColor, QPaintEvent, QPainter, QPainterPath, QPalette, QPen
        from PyQt5.QtWidgets import QApplication, QWidget
    except ImportError:  # pragma: no cover - static tooling outside IDA
        QApplication = None  # type: ignore[assignment]
        QWidget = object  # type: ignore[assignment,misc]
        QEvent = QObject = QRectF = Qt = QColor = QPaintEvent = None  # type: ignore[assignment]
        QPainter = None  # type: ignore[assignment]
        QPainterPath = QPalette = QPen = None  # type: ignore[assignment]

from .palette import c as _themed
from .qt_compat import qobject_key, same_qobject


_NAVBAND_CLASS = "navband_t"
_NAVIGATOR_CLASS = "navigator_t"
_LABEL_CLASS = "ui_label_t"
_PLUGIN_MARKER = "modernUiPluginPanel"
_SWATCH_PROPERTY = "modernUiNavLegendSwatch"
_SWATCH_VALUE = True

# Keep the native hit area (32 logical px in IDA 9.3), but make the painted
# rail feel lighter.  Values are deliberately conservative for high-DPI and
# older IDA layouts where the band can be shorter than usual.
_INSET_X = 2.0
# The 32-logical-pixel native rail becomes about 22 logical pixels visually
# (roughly 33 physical pixels at the user's 150% scale), while the full native
# rectangle remains available for clicking and dragging.
_INSET_Y = 5.0
_RADIUS = 6.0
_BORDER_COLOR = "#303946"
_BACKGROUND_COLOR = "#111319"


def _enum(owner: Any, nested: str, name: str, fallback: Any = None) -> Any:
    if owner is None:
        return fallback
    group = getattr(owner, nested, owner)
    return getattr(group, name, getattr(owner, name, fallback))


def _event_type(name: str) -> Any:
    return _enum(QEvent, "Type", name, getattr(QEvent, name, None) if QEvent else None)


_PAINT_EVENT = _event_type("Paint")
_RESIZE_EVENT = _event_type("Resize")
_SHOW_EVENT = _event_type("Show")
_STYLE_EVENT = _event_type("StyleChange")
_PALETTE_EVENT = _event_type("PaletteChange")
_NO_PEN = _enum(Qt, "PenStyle", "NoPen", getattr(Qt, "NoPen", None) if Qt else None)
_NO_BRUSH = _enum(Qt, "BrushStyle", "NoBrush", getattr(Qt, "NoBrush", None) if Qt else None)
_ODD_EVEN = _enum(
    Qt,
    "FillRule",
    "OddEvenFill",
    getattr(Qt, "OddEvenFill", None) if Qt else None,
)
_ANTIALIASING = _enum(
    QPainter,
    "RenderHint",
    "Antialiasing",
    getattr(QPainter, "Antialiasing", None) if QPainter else None,
)


def _class_chain(widget: Any) -> tuple[str, ...]:
    names = []
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


def _has_class(widget: Any, class_name: str) -> bool:
    return class_name in _class_chain(widget)


def _ancestors(widget: Any) -> Iterable[Any]:
    current = widget
    seen = set()
    while current is not None:
        key = qobject_key(current)
        if key in seen:
            break
        seen.add(key)
        yield current
        try:
            current = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            break


def _inside_navigator(widget: Any) -> bool:
    return any(_has_class(parent, _NAVIGATOR_CLASS) for parent in _ancestors(widget))


def _is_swatch(widget: Any) -> bool:
    """Recognise only the fixed-size legend chips, not text labels."""

    if not _has_class(widget, _LABEL_CLASS) or not _inside_navigator(widget):
        return False
    for ancestor in _ancestors(widget):
        try:
            if bool(ancestor.property(_PLUGIN_MARKER)):
                return False
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
    try:
        width = int(widget.width())
        height = int(widget.height())
        minimum = widget.minimumSize()
        min_width = int(minimum.width())
        min_height = int(minimum.height())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    # IDA's legend chips are 15x15 with a fixed minimum.  Keep a little
    # tolerance for a 125%/150% DPI layout while excluding the 1x4 and text
    # labels in the same legend row.
    return (
        12 <= width <= 28
        and 12 <= height <= 28
        and abs(width - height) <= 4
        and 12 <= min_width <= 28
        and 12 <= min_height <= 28
    )


def _background(widget: Any) -> QColor:
    """Use the native dark base when available; avoid a bright palette seam."""

    try:
        palette = widget.palette()
        role = _enum(QPalette, "ColorRole", "Base", getattr(QPalette, "Base", None))
        color = palette.color(role)
        if color.isValid() and color.alpha() > 0:
            name = color.name().upper()
            if name not in {"#000000", "#FFFFFF"}:
                return QColor(color)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return QColor(_themed(_BACKGROUND_COLOR))


class _NavbandPaintFilter(QObject):
    """Filter attached to one ``navband_t`` only (never QApplication-wide)."""

    def __init__(self, target: Any, runtime: "_NavbandRuntime") -> None:
        super().__init__(runtime)
        self._target = target
        self._runtime = runtime
        self._painting = False

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - Qt API
        if not self._runtime.enabled or not same_qobject(watched, self._target):
            return False
        try:
            event_type = event.type()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        if event_type == _PAINT_EVENT:
            return self._paint_once(watched)
        if event_type in {
            _RESIZE_EVENT,
            _SHOW_EVENT,
            _STYLE_EVENT,
            _PALETTE_EVENT,
        }:
            try:
                watched.update()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        return False

    def _paint_once(self, target: Any) -> bool:
        if self._painting or QPainter is None or QPaintEvent is None:
            return False
        app = QApplication.instance() if QApplication is not None else None
        if app is None:
            return False
        try:
            rect = target.rect()
            if rect.width() <= 3 or rect.height() <= 3:
                return False
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

        # Let IDA render all native segments/cursor first.  The recursion guard
        # prevents this synthetic event from entering this filter again.
        self._painting = True
        try:
            app.sendEvent(target, QPaintEvent(rect))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        finally:
            self._painting = False

        try:
            self._draw_mask(target)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            # Native content is already on screen; never turn a cosmetic
            # failure into a blank navigation band.
            pass
        return True

    def _draw_mask(self, target: Any) -> None:
        rect = target.rect()
        width = float(rect.width())
        height = float(rect.height())
        inset_x = min(_INSET_X, max(0.0, width / 4.0))
        inset_y = min(_INSET_Y, max(0.0, height / 4.0))
        inner = QRectF(rect).adjusted(inset_x, inset_y, -inset_x, -inset_y)
        if inner.width() <= 2.0 or inner.height() <= 2.0:
            return
        radius = min(
            self._runtime.visual_radius,
            inner.width() / 2.0,
            inner.height() / 2.0,
        )
        painter = QPainter(target)
        try:
            if _ANTIALIASING is not None:
                painter.setRenderHint(_ANTIALIASING, True)
            if _NO_PEN is not None:
                painter.setPen(_NO_PEN)
            outside = QPainterPath()
            outside.addRect(QRectF(rect))
            outside.addRoundedRect(inner, radius, radius)
            if _ODD_EVEN is not None:
                outside.setFillRule(_ODD_EVEN)
            painter.fillPath(outside, _background(target))
            border = QColor(_themed(_BORDER_COLOR))
            border.setAlpha(190)
            painter.setBrush(_NO_BRUSH if _NO_BRUSH is not None else border)
            painter.setPen(QPen(border, 1.0))
            outlined = inner.adjusted(0.5, 0.5, -0.5, -0.5)
            painter.drawRoundedRect(
                outlined,
                max(1.0, radius - 0.5),
                max(1.0, radius - 0.5),
            )
        finally:
            painter.end()


class _SwatchPaintFilter(QObject):
    """Round one legend chip after ``ui_label_t`` has painted its colour."""

    def __init__(self, target: Any, runtime: "_NavbandRuntime") -> None:
        super().__init__(runtime)
        self._target = target
        self._runtime = runtime
        self._painting = False

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - Qt API
        if not self._runtime.enabled or not same_qobject(watched, self._target):
            return False
        try:
            event_type = event.type()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        if event_type == _PAINT_EVENT:
            return self._paint_once(watched)
        if event_type in {
            _RESIZE_EVENT,
            _SHOW_EVENT,
            _STYLE_EVENT,
            _PALETTE_EVENT,
        }:
            try:
                watched.update()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        return False

    def _paint_once(self, target: Any) -> bool:
        if self._painting or QPainter is None or QPaintEvent is None:
            return False
        app = QApplication.instance() if QApplication is not None else None
        if app is None:
            return False
        try:
            rect = target.rect()
            if rect.width() <= 2 or rect.height() <= 2:
                return False
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        self._painting = True
        try:
            app.sendEvent(target, QPaintEvent(rect))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        finally:
            self._painting = False
        try:
            self._draw_mask(target)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        return True

    @staticmethod
    def _draw_mask(target: Any) -> None:
        if QPainter is None:
            return
        rect = target.rect()
        inner = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
        if inner.width() <= 2.0 or inner.height() <= 2.0:
            return
        radius = min(4.0, inner.width() / 2.0, inner.height() / 2.0)
        outside = QPainterPath()
        outside.addRect(QRectF(rect))
        outside.addRoundedRect(inner, radius, radius)
        if _ODD_EVEN is not None:
            outside.setFillRule(_ODD_EVEN)
        parent = None
        try:
            parent = target.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        painter = QPainter(target)
        try:
            if _ANTIALIASING is not None:
                painter.setRenderHint(_ANTIALIASING, True)
            if _NO_PEN is not None:
                painter.setPen(_NO_PEN)
            painter.fillPath(outside, _background(parent or target))
        finally:
            painter.end()



@dataclass
class _NavbandEntry:
    target: Any
    filter: _NavbandPaintFilter


class _NavbandRuntime(QObject):
    def __init__(self) -> None:
        if QObject is not None:
            super().__init__()
        self.enabled = False
        self.visual_radius = _RADIUS
        self._entries: Dict[Any, _NavbandEntry] = {}
        self._swatches: Dict[Any, Any] = {}
        self._swatch_filters: Dict[Any, _SwatchPaintFilter] = {}
        self._scan_count = 0
        self._attach_count = 0

    def apply(self, root: Any = None, corner_radius: Optional[int] = None) -> None:
        if QApplication is None or QWidget is object:
            return
        if corner_radius is not None:
            try:
                # Keep the band visually lighter than a full-size card while
                # still following the user's global corner-radius setting.
                self.visual_radius = max(0.0, min(8.0, float(corner_radius) * 0.6))
            except (TypeError, ValueError):
                self.visual_radius = _RADIUS
        self.enabled = True
        if self.visual_radius <= 0.0:
            self._detach_all()
            self._unmark_swatches()
            return
        self._scan_count += 1
        for widget in self._iter_widgets(root):
            if _has_class(widget, _NAVBAND_CLASS):
                self._attach(widget)
            if _is_swatch(widget):
                self._mark_swatch(widget)
        self._prune()

    def refresh(self, root: Any = None) -> None:
        if self.enabled:
            self.apply(root)

    def restore(self) -> None:
        self.enabled = False
        self._detach_all()
        self._unmark_swatches()
        self.visual_radius = _RADIUS

    def _detach_all(self) -> None:
        entries = list(self._entries.values())
        self._entries.clear()
        for entry in entries:
            try:
                entry.target.removeEventFilter(entry.filter)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            try:
                entry.filter.deleteLater()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass

    def _unmark_swatches(self) -> None:
        swatches = list(self._swatches.items())
        self._swatches.clear()
        filters = self._swatch_filters
        self._swatch_filters = {}
        for key, swatch in swatches:
            paint_filter = filters.get(key)
            if paint_filter is not None:
                try:
                    swatch.removeEventFilter(paint_filter)
                    paint_filter.deleteLater()
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
            self._clear_swatch(swatch)

    @staticmethod
    def _clear_swatch(swatch: Any) -> None:
        """Drop the marker from one live label (destroyed wrappers are benign)."""

        try:
            swatch.setProperty(_SWATCH_PROPERTY, None)
            swatch.style().unpolish(swatch)
            swatch.style().polish(swatch)
            swatch.update()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    def _prune_swatches(self) -> None:
        stale = []
        for key, swatch in tuple(self._swatches.items()):
            try:
                if not _is_swatch(swatch):
                    stale.append((key, swatch))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                stale.append((key, swatch))
        for key, swatch in stale:
            self._swatches.pop(key, None)
            paint_filter = self._swatch_filters.pop(key, None)
            try:
                if paint_filter is not None:
                    swatch.removeEventFilter(paint_filter)
                    paint_filter.deleteLater()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            self._clear_swatch(swatch)

    def diagnostics(self) -> dict:
        return {
            "enabled": bool(self.enabled),
            "navband_count": len(self._entries),
            "legend_swatch_count": len(self._swatches),
            "scan_count": int(self._scan_count),
            "attach_count": int(self._attach_count),
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
        for candidate_root in roots:
            candidates = [candidate_root]
            try:
                candidates.extend(candidate_root.findChildren(QWidget))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            for widget in candidates:
                key = qobject_key(widget)
                if key in seen:
                    continue
                seen.add(key)
                yield widget

    def _attach(self, target: Any) -> None:
        key = qobject_key(target)
        if key in self._entries:
            return
        try:
            paint_filter = _NavbandPaintFilter(target, self)
            target.installEventFilter(paint_filter)
            self._entries[key] = _NavbandEntry(target, paint_filter)
            self._attach_count += 1
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

    def _mark_swatch(self, swatch: Any) -> None:
        key = qobject_key(swatch)
        if key in self._swatches:
            return
        try:
            # Preserve an explicit opt-out used by a future IDA build/plugin.
            if bool(swatch.property("modernUiNavLegendOptOut")):
                return
            self._swatches[key] = swatch
            paint_filter = _SwatchPaintFilter(swatch, self)
            swatch.installEventFilter(paint_filter)
            self._swatch_filters[key] = paint_filter
            swatch.setProperty(_SWATCH_PROPERTY, _SWATCH_VALUE)
            style = swatch.style()
            style.unpolish(swatch)
            style.polish(swatch)
            swatch.update()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self._swatches.pop(key, None)
            paint_filter = self._swatch_filters.pop(key, None)
            if paint_filter is not None:
                try:
                    swatch.removeEventFilter(paint_filter)
                    paint_filter.deleteLater()
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass

    def _prune(self) -> None:
        stale = []
        for key, entry in tuple(self._entries.items()):
            try:
                if entry.target is None or not _has_class(entry.target, _NAVBAND_CLASS):
                    stale.append(key)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                stale.append(key)
        for key in stale:
            entry = self._entries.pop(key, None)
            if entry is None:
                continue
            try:
                entry.target.removeEventFilter(entry.filter)
                entry.filter.deleteLater()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        self._prune_swatches()


_RUNTIME = _NavbandRuntime() if QObject is not None else None


def apply_navband_runtime(root: Any = None, corner_radius: Optional[int] = None) -> None:
    """Attach local rounded navigation-band overlays (idempotent)."""

    if _RUNTIME is not None:
        _RUNTIME.apply(root, corner_radius)


def refresh_navband_runtime(root: Any = None) -> None:
    if _RUNTIME is not None:
        _RUNTIME.refresh(root)


def restore_navband_runtime() -> None:
    if _RUNTIME is not None:
        _RUNTIME.restore()


def navband_runtime_diagnostics() -> dict:
    if _RUNTIME is None:
        return {"enabled": False, "navband_count": 0, "legend_swatch_count": 0}
    return _RUNTIME.diagnostics()


__all__ = [
    "apply_navband_runtime",
    "refresh_navband_runtime",
    "restore_navband_runtime",
    "navband_runtime_diagnostics",
]
