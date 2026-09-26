# -*- coding: utf-8 -*-
"""Narrow runtime styling for IDA's custom dock controls.

IDA paints its docking drop targets itself, so application QSS cannot recolor
the old white/purple ``DockArrow`` controls.  This module deliberately handles
only those exact meta-object classes and dock-title close buttons.  Normal Qt
widgets (including third-party plugin panels) continue through their original
paint path.
"""

from __future__ import annotations

import weakref

from .palette import c as _themed
from .qt_compat import (
    QAbstractButton,
    QApplication,
    QBrush,
    QColor,
    QCursor,
    QEvent,
    QObject,
    QPainter,
    QPen,
    QPointF,
    QRectF,
    Qt,
    qobject_key,
    same_qobject,
    QWidget,
)


_ARROW_CLASS = "DockArrow"
_ARROW_AREA_CLASS = "DockArrowArea"
_TITLE_CLASSES = ("DockWidgetTitle", "DockAreaDragTitle")

# The native central guide is 89x89 logical pixels.  The generous upper bound
# protects against a future IDA class with the same name being used as a full
# window overlay: in that case we leave its native painter untouched.
_MIN_GUIDE_SIZE = 12
_MAX_GUIDE_SIZE = 180

_ROLE_ARROW = "arrow"
_ROLE_ARROW_AREA = "arrow-area"
_ROLE_CLOSE = "close"
_ROLE_TITLE_ACTION = "title-action"

_runtime_controller = None


class _StrongReference:
    """Callable reference used for short-lived native title-button wrappers.

    ``QApplication.allWidgets()`` can return temporary Python wrappers for
    IDA's native title controls.  A weakref would disappear before the next
    paint event even though the C++ widget is still alive, so retain only
    these few title controls strongly and let the normal RuntimeError/stale
    cleanup path release them after Qt destroys the object.
    """

    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def _enum(owner, group_name, value_name):
    """Return an enum value with both Qt 5 and Qt 6 naming layouts."""
    group = getattr(owner, group_name, owner)
    return getattr(group, value_name)


def _event_type(name):
    return _enum(QEvent, "Type", name)


_PAINT_EVENT = _event_type("Paint")
_SHOW_EVENT = _event_type("Show")
_CHILD_ADDED_EVENT = _event_type("ChildAdded")
_LAYOUT_REQUEST_EVENT = _event_type("LayoutRequest")
_POLISH_EVENT = _event_type("Polish")
_WA_TRANSLUCENT_BACKGROUND = _enum(
    Qt, "WidgetAttribute", "WA_TranslucentBackground"
)
_WA_OPAQUE_PAINT_EVENT = _enum(Qt, "WidgetAttribute", "WA_OpaquePaintEvent")
_WA_NO_SYSTEM_BACKGROUND = _enum(Qt, "WidgetAttribute", "WA_NoSystemBackground")


def _meta_class_names(widget):
    """Yield the C++ meta-object hierarchy without relying on Python wrappers."""
    try:
        meta = widget.metaObject()
        while meta is not None:
            yield str(meta.className())
            meta = meta.superClass()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return


def _nearest_title(widget):
    try:
        current = widget.parentWidget()
    except (AttributeError, RuntimeError):
        return None
    while current is not None:
        if set(_meta_class_names(current)).intersection(_TITLE_CLASSES):
            return current
        try:
            current = current.parentWidget()
        except (AttributeError, RuntimeError):
            return None
    return None


def _valid_guide_size(widget):
    try:
        width = int(widget.width())
        height = int(widget.height())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    return (
        _MIN_GUIDE_SIZE <= width <= _MAX_GUIDE_SIZE
        and _MIN_GUIDE_SIZE <= height <= _MAX_GUIDE_SIZE
    )


def _color(value, alpha=None):
    color = QColor(_themed(value) if isinstance(value, str) else value)
    if not color.isValid():
        color = QColor("#82AAFF")
    if alpha is not None:
        color.setAlpha(int(alpha))
    return color


def _mix(left, right, ratio):
    ratio = max(0.0, min(1.0, float(ratio)))
    return QColor(
        round(left.red() + (right.red() - left.red()) * ratio),
        round(left.green() + (right.green() - left.green()) * ratio),
        round(left.blue() + (right.blue() - left.blue()) * ratio),
        round(left.alpha() + (right.alpha() - left.alpha()) * ratio),
    )


def _global_center(widget):
    try:
        point = widget.mapToGlobal(widget.rect().center())
        return QPointF(float(point.x()), float(point.y()))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _cursor_inside(widget):
    try:
        local = widget.mapFromGlobal(QCursor.pos())
        return widget.rect().contains(local)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


class _DockTargetPaintFilter(QObject):
    """Paint filter installed only on the handful of registered dock targets."""

    def __init__(self, controller):
        super().__init__(controller)
        self._controller = controller

    def eventFilter(self, watched, event):
        controller = self._controller
        if not controller.enabled:
            return False
        try:
            # Native dock titles are sometimes created one layout pass after
            # IDA's widget_visible hook.  A local, dirty-only watcher on the
            # nearest DockArea/DockWidget catches that child creation without
            # introducing an application-wide event filter or a resize timer.
            controller._watcher_event(watched, event)
            if event.type() != _PAINT_EVENT:
                return False
            record = controller._target_record(watched)
            if record is None:
                return False
            role, title = record
            if role == _ROLE_ARROW_AREA:
                if _valid_guide_size(watched):
                    return controller._paint_arrow_area(watched)
                return False
            if role == _ROLE_ARROW:
                if _valid_guide_size(watched):
                    return controller._paint_arrow(watched)
                return False
            if role == _ROLE_CLOSE:
                return controller._paint_close_button(watched, title)
            if role == _ROLE_TITLE_ACTION:
                return controller._paint_title_action(watched, title)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            # Transient guides may be deleted while a queued paint still owns
            # their Python wrapper. Let Qt discard or paint what survived.
            return False
        return False


class _DockRuntimeController(QObject):
    """Own only local target filters; QApplication never enters Python here."""

    _DOCK_CONTAINER_CLASSES = {
        "DockArea",
        "TopLevelDockArea",
        "DockWidget",
        "IDADockWidget",
        "BaseDockWidget",
        "ComplexDockWidget",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = False
        self.accent = _color("#82AAFF")
        self.radius = 4.0
        self.scan_count = 0
        self._areas = {}
        self._targets = {}
        # Strong references are kept only for the small set of native dock
        # containers/titles that need a deferred child-creation observation.
        # Each record is (callable reference, dirty flag).
        self._watchers = {}
        self._backgrounds = {}
        self._paint_filter = _DockTargetPaintFilter(self)

    def configure(self, accent, radius):
        candidate = _color(accent)
        self.accent = candidate if candidate.isValid() else _color("#82AAFF")
        self.radius = max(3.0, min(7.0, float(radius)))
        self.enabled = True

    def deactivate(self):
        self.enabled = False
        targets = list(self._live_targets())
        watchers = list(self._live_watchers())
        self._targets.clear()
        self._watchers.clear()
        self._areas.clear()
        for widget, _role, _title in targets:
            try:
                widget.removeEventFilter(self._paint_filter)
                widget.update()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        for widget in watchers:
            try:
                widget.removeEventFilter(self._paint_filter)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        self._restore_backgrounds()

    def discover_existing(self, app):
        """Synchronously inventory existing widgets at one lifecycle boundary."""
        self.scan_count += 1
        try:
            widgets = app.allWidgets()
        except (AttributeError, RuntimeError, TypeError):
            return
        for widget in widgets:
            self._register_watcher(widget)
            self._register_target(widget)

    def update_targets(self):
        """Repaint cached targets after a settings preview without rescanning."""
        for widget, _role, _title in list(self._live_targets()):
            try:
                widget.update()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue

    def diagnostics(self):
        """Return cache-only counters; never inspect QApplication or widget trees."""
        role_counts = {
            _ROLE_ARROW: 0,
            _ROLE_ARROW_AREA: 0,
            _ROLE_CLOSE: 0,
            _ROLE_TITLE_ACTION: 0,
        }
        for _reference, role, _title_reference in tuple(self._targets.values()):
            if role in role_counts:
                role_counts[role] += 1
        return {
            "enabled": bool(self.enabled),
            "scan_count": int(self.scan_count),
            "target_counts": role_counts,
        }

    def refresh(self, widget):
        """Scan one low-frequency UI-hook widget and its dock neighbourhood."""
        if not self.enabled or widget is None:
            return

        seen = set()
        self._scan_tree(widget, seen)
        dock_roots = []
        current = widget
        while current is not None:
            key = id(current)
            if key not in seen:
                seen.add(key)
                self._register_watcher(current)
                self._register_target(current)
            names = set(_meta_class_names(current))
            if names.intersection(_TITLE_CLASSES):
                self._scan_title_buttons(current, seen)
            if self._is_dock_container(names) and len(dock_roots) < 2:
                dock_roots.append(current)
            try:
                current = current.parentWidget()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                break

        # The converted IDA TWidget is normally the dock content. Its title is
        # a sibling, while transient arrows live in the enclosing DockArea.
        # Scan at most the two nearest dock containers, and only from this
        # widget-visible hook (never from resize/paint events).
        for root in dock_roots:
            self._scan_tree(root, seen)

    def _scan_tree(self, root, seen):
        if root is None:
            return
        key = id(root)
        if key not in seen:
            seen.add(key)
            self._register_watcher(root)
            self._register_target(root)
            if set(_meta_class_names(root)).intersection(_TITLE_CLASSES):
                self._scan_title_buttons(root, seen)
        try:
            descendants = root.findChildren(QWidget)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            descendants = []
        for candidate in descendants:
            key = id(candidate)
            if key in seen:
                continue
            seen.add(key)
            self._register_watcher(candidate)
            self._register_target(candidate)
            if set(_meta_class_names(candidate)).intersection(_TITLE_CLASSES):
                self._scan_title_buttons(candidate, seen)

    def _scan_title_buttons(self, title, seen):
        try:
            buttons = title.findChildren(QAbstractButton)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            buttons = []
        for button in buttons:
            key = id(button)
            if key in seen:
                continue
            seen.add(key)
            self._register_target(button)

    @classmethod
    def _is_dock_container(cls, names):
        if names.intersection(cls._DOCK_CONTAINER_CLASSES):
            return True
        return any(
            name.endswith("DockWidget") or name.endswith("DockArea")
            for name in names
        )

    @staticmethod
    def _object_key(widget):
        """Use the C++ identity when a fresh Python wrapper is returned."""
        try:
            key = qobject_key(widget)
            if key is not None:
                return key
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        return ("python", id(widget))

    def _register_watcher(self, widget):
        """Watch one local dock host for a deferred native title layout."""
        if widget is None:
            return
        try:
            names = set(_meta_class_names(widget))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return
        if not (
            names.intersection(_TITLE_CLASSES)
            or self._is_dock_container(names)
        ):
            return
        key = self._object_key(widget)
        current = self._watchers.get(key)
        if current is not None:
            try:
                if same_qobject(current[0](), widget):
                    return
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        try:
            widget.installEventFilter(self._paint_filter)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return
        self._watchers[key] = (_StrongReference(widget), True)

    def _live_watchers(self):
        stale = []
        for key, (reference, _dirty) in list(self._watchers.items()):
            try:
                widget = reference()
                if widget is None:
                    stale.append((key, reference))
                    continue
                # Touching the C++ object detects a wrapper whose dock was
                # destroyed while a queued event still owns the Python proxy.
                widget.isVisible()
                yield widget
            except (AttributeError, RuntimeError, TypeError, ValueError):
                stale.append((key, reference))
        for key, reference in stale:
            record = self._watchers.get(key)
            if record is not None and record[0] is reference:
                self._watchers.pop(key, None)

    def _scan_watch_neighborhood(self, watched):
        """Inventory a just-laid-out dock and its nearest two ancestors."""
        roots = []
        current = watched
        for _ in range(3):
            if current is None:
                break
            if not any(same_qobject(current, root) for root in roots):
                roots.append(current)
            try:
                current = current.parentWidget()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                break
        seen = set()
        for root in roots:
            self._scan_tree(root, seen)
        for root in roots:
            key = self._object_key(root)
            record = self._watchers.get(key)
            if record is not None:
                self._watchers[key] = (record[0], False)

    def _watcher_event(self, watched, event):
        """Handle only dirty local-host events; return False for Qt."""
        try:
            event_type = event.type()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        if event_type not in {
            _SHOW_EVENT,
            _CHILD_ADDED_EVENT,
            _LAYOUT_REQUEST_EVENT,
            _POLISH_EVENT,
            _PAINT_EVENT,
        }:
            return False
        key = self._object_key(watched)
        record = self._watchers.get(key)
        if record is None:
            return False
        reference, dirty = record
        if event_type == _CHILD_ADDED_EVENT:
            self._watchers[key] = (reference, True)
            return False
        if not dirty:
            return False
        # A title can be painted immediately after a ChildAdded event, while
        # a dock container generally emits LayoutRequest/Show.  Either is a
        # safe one-shot boundary to discover the now-sized buttons.
        self._scan_watch_neighborhood(watched)
        return False

    def _classify_target(self, widget):
        names = set(_meta_class_names(widget))
        if _ARROW_AREA_CLASS in names:
            return _ROLE_ARROW_AREA, None
        if _ARROW_CLASS in names:
            return _ROLE_ARROW, None
        if isinstance(widget, QAbstractButton):
            title = _nearest_title(widget)
            if title is not None:
                if self._is_close_button(widget, title):
                    return _ROLE_CLOSE, title
                if self._is_title_action_button(widget, title):
                    return _ROLE_TITLE_ACTION, title
        return None, None

    def _register_target(self, widget):
        try:
            key = id(widget)
            current = self._targets.get(key)
            if current is not None and same_qobject(current[0](), widget):
                widget.update()
                return

            role, title = self._classify_target(widget)
            if role is None:
                return

            if role in (_ROLE_CLOSE, _ROLE_TITLE_ACTION):
                # Keep native title wrappers alive through the paint event.
                reference = _StrongReference(widget)
                title_reference = _StrongReference(title) if title is not None else None
            else:
                controller_reference = weakref.ref(self)

                def remove_dead(reference, target_key=key, owner=controller_reference):
                    controller = owner()
                    if controller is None:
                        return
                    record = controller._targets.get(target_key)
                    if record is not None and record[0] is reference:
                        controller._targets.pop(target_key, None)
                    area = controller._areas.get(target_key)
                    if area is reference:
                        controller._areas.pop(target_key, None)

                reference = weakref.ref(widget, remove_dead)
                try:
                    title_reference = weakref.ref(title) if title is not None else None
                except TypeError:
                    title_reference = None

            self._targets[key] = (reference, role, title_reference)
            widget.installEventFilter(self._paint_filter)
            if role in (_ROLE_ARROW, _ROLE_ARROW_AREA):
                self._prepare_transparent_background(widget)
            if role == _ROLE_ARROW_AREA:
                self._areas[key] = reference
                self._prepare_small_guide_container(widget)
            widget.update()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

    def _target_record(self, widget):
        key = id(widget)
        record = self._targets.get(key)
        if record is None:
            return None
        try:
            if same_qobject(record[0](), widget):
                title = record[2]() if record[2] is not None else None
                return record[1], title
        except (RuntimeError, TypeError):
            pass
        if self._targets.get(key) is record:
            self._targets.pop(key, None)
        if self._areas.get(key) is record[0]:
            self._areas.pop(key, None)
        return None

    def _live_targets(self):
        stale = []
        for key, (reference, role, title_reference) in list(self._targets.items()):
            try:
                widget = reference()
                if widget is None:
                    stale.append((key, reference))
                    continue
                title = title_reference() if title_reference is not None else None
                yield widget, role, title
            except (RuntimeError, TypeError):
                stale.append((key, reference))
        for key, reference in stale:
            record = self._targets.get(key)
            if record is not None and record[0] is reference:
                self._targets.pop(key, None)
            if self._areas.get(key) is reference:
                self._areas.pop(key, None)

    def _prepare_transparent_background(self, widget):
        """Make one guide surface transparent and remember every changed flag."""
        key = id(widget)
        current = self._backgrounds.get(key)
        if current is not None:
            try:
                if current[0]() is widget:
                    return
            except (RuntimeError, TypeError):
                pass

        try:
            auto_fill = bool(widget.autoFillBackground())
            translucent = bool(widget.testAttribute(_WA_TRANSLUCENT_BACKGROUND))
            opaque = bool(widget.testAttribute(_WA_OPAQUE_PAINT_EVENT))
            no_system = bool(widget.testAttribute(_WA_NO_SYSTEM_BACKGROUND))
            style_sheet = str(widget.styleSheet())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

        controller_reference = weakref.ref(self)

        def remove_dead(reference, background_key=key, owner=controller_reference):
            controller = owner()
            if controller is None:
                return
            record = controller._backgrounds.get(background_key)
            if record is not None and record[0] is reference:
                controller._backgrounds.pop(background_key, None)

        try:
            reference = weakref.ref(widget, remove_dead)
        except TypeError:
            return
        self._backgrounds[key] = (
            reference,
            auto_fill,
            translucent,
            opaque,
            no_system,
            style_sheet,
        )
        try:
            # A local stylesheet wins over the application-wide QWidget
            # background rule which otherwise repaints the compact DockArea as
            # a black rectangular plate behind the rounded five-way guide.
            widget.setStyleSheet("background: transparent; border: 0;")
            widget.setAutoFillBackground(False)
            widget.setAttribute(_WA_TRANSLUCENT_BACKGROUND, True)
            widget.setAttribute(_WA_OPAQUE_PAINT_EVENT, False)
            widget.setAttribute(_WA_NO_SYSTEM_BACKGROUND, True)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            # Keep the snapshot: restore will put back any flags changed before
            # a transient wrapper became invalid.
            pass

    def _prepare_small_guide_container(self, widget):
        """Clear the compact DockArea plate behind the 89x89 center guide."""
        try:
            parent = widget.parentWidget()
            if parent is None:
                return
            names = set(_meta_class_names(parent))
            width = int(parent.width())
            height = int(parent.height())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return
        if (
            "DockArea" in names
            and _MIN_GUIDE_SIZE <= width <= _MAX_GUIDE_SIZE + 80
            and _MIN_GUIDE_SIZE <= height <= _MAX_GUIDE_SIZE + 80
        ):
            self._prepare_transparent_background(parent)

    def _restore_backgrounds(self):
        records = list(self._backgrounds.values())
        self._backgrounds.clear()
        for (
            reference,
            auto_fill,
            translucent,
            opaque,
            no_system,
            style_sheet,
        ) in records:
            try:
                widget = reference()
                if widget is None:
                    continue
                widget.setStyleSheet(style_sheet)
                widget.setAttribute(_WA_TRANSLUCENT_BACKGROUND, translucent)
                widget.setAttribute(_WA_OPAQUE_PAINT_EVENT, opaque)
                widget.setAttribute(_WA_NO_SYSTEM_BACKGROUND, no_system)
                widget.setAutoFillBackground(auto_fill)
                widget.update()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue

    def _area_centers(self):
        centers = []
        stale = []
        for key, reference in list(self._areas.items()):
            record = self._targets.get(key)
            if record is None or record[0] is not reference:
                stale.append((key, reference))
                continue
            try:
                widget = reference()
                if widget is None:
                    stale.append((key, reference))
                    continue
                if widget.isVisible() and _valid_guide_size(widget):
                    center = _global_center(widget)
                    if center is not None:
                        centers.append(center)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                stale.append((key, reference))
        for key, reference in stale:
            if self._areas.get(key) is reference:
                self._areas.pop(key, None)
        return centers
    def _direction_hint(self, widget):
        """Prefer a semantic hint, then compare with the central guide."""
        labels = []
        for accessor in ("objectName", "toolTip", "statusTip", "accessibleName"):
            try:
                labels.append(str(getattr(widget, accessor)()))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        for property_name in ("direction", "arrowType", "position", "dockArea"):
            try:
                labels.append(str(widget.property(property_name)))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        hint = " ".join(labels).casefold()
        word_groups = (
            ("left", ("left", "west")),
            ("right", ("right", "east")),
            ("up", ("up", "top", "north")),
            ("down", ("down", "bottom", "south")),
        )
        for direction, words in word_groups:
            if any(word in hint for word in words):
                return direction

        center = _global_center(widget)
        if center is None:
            return "down"
        anchors = self._area_centers()
        if anchors:
            anchor = min(
                anchors,
                key=lambda point: (point.x() - center.x()) ** 2
                + (point.y() - center.y()) ** 2,
            )
        else:
            anchor = self._fallback_anchor(widget)
        if anchor is None:
            return "down"

        delta_x = center.x() - anchor.x()
        delta_y = center.y() - anchor.y()
        if abs(delta_x) > abs(delta_y):
            return "right" if delta_x >= 0 else "left"
        return "down" if delta_y >= 0 else "up"

    @staticmethod
    def _fallback_anchor(widget):
        """Use the nearest sizeable ancestor if the center target is not seen yet."""
        try:
            current = widget.parentWidget()
        except (AttributeError, RuntimeError):
            current = None
        while current is not None:
            try:
                if current.width() > _MAX_GUIDE_SIZE or current.height() > _MAX_GUIDE_SIZE:
                    return _global_center(current)
                current = current.parentWidget()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                break
        app = QApplication.instance()
        if app is not None:
            try:
                window = app.activeWindow()
                if window is not None:
                    return _global_center(window)
            except (AttributeError, RuntimeError):
                pass
        return None

    def _new_painter(self, widget):
        painter = QPainter(widget)
        if not painter.isActive():
            return None
        painter.setRenderHint(_enum(QPainter, "RenderHint", "Antialiasing"), True)
        return painter

    @staticmethod
    def _clear_translucent(painter, widget):
        painter.save()
        painter.setCompositionMode(
            _enum(QPainter, "CompositionMode", "CompositionMode_Source")
        )
        painter.fillRect(QRectF(widget.rect()), QColor(0, 0, 0, 0))
        painter.restore()

    def _paint_arrow_area(self, widget):
        painter = self._new_painter(widget)
        if painter is None:
            return False
        try:
            self._clear_translucent(painter, widget)
            bounds = QRectF(widget.rect())
            extent = min(bounds.width(), bounds.height())
            outer_padding = max(1.0, min(2.5, extent * 0.025))
            gap = max(2.0, min(4.0, extent * 0.038))
            side = (extent - 2.0 * outer_padding - 2.0 * gap) / 3.0
            if side < 7.0:
                return False

            total = side * 3.0 + gap * 2.0
            start_x = bounds.center().x() - total / 2.0
            start_y = bounds.center().y() - total / 2.0
            positions = {
                "up": (1, 0),
                "left": (0, 1),
                "center": (1, 1),
                "right": (2, 1),
                "down": (1, 2),
            }
            try:
                cursor = widget.mapFromGlobal(QCursor.pos())
                cursor_point = QPointF(float(cursor.x()), float(cursor.y()))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                cursor_point = QPointF(-1.0, -1.0)

            for direction, (column, row) in positions.items():
                target = QRectF(
                    start_x + column * (side + gap),
                    start_y + row * (side + gap),
                    side,
                    side,
                )
                self._draw_target(
                    painter,
                    target,
                    direction,
                    target.contains(cursor_point),
                )
            return True
        finally:
            painter.end()

    def _paint_arrow(self, widget):
        painter = self._new_painter(widget)
        if painter is None:
            return False
        try:
            self._clear_translucent(painter, widget)
            bounds = QRectF(widget.rect())
            inset = max(1.0, min(2.5, min(bounds.width(), bounds.height()) * 0.055))
            target = bounds.adjusted(inset, inset, -inset, -inset)
            self._draw_target(
                painter,
                target,
                self._direction_hint(widget),
                _cursor_inside(widget),
            )
            return True
        finally:
            painter.end()

    def _draw_target(self, painter, rect, direction, active):
        """Draw a compact dark target with a side/center docking preview."""
        accent = self.accent
        base = _color("#202631", 246)
        border = _color("#566276", 235)
        if active:
            base = _mix(base, accent, 0.18)
            border = QColor(accent)
            border.setAlpha(245)

        radius = min(self.radius, rect.width() * 0.19, rect.height() * 0.19)
        shadow = rect.translated(0.0, max(0.8, rect.height() * 0.035))
        painter.setPen(QPen(_color("#080A0E", 120), 0.8))
        painter.setBrush(QBrush(_color("#080A0E", 115)))
        painter.drawRoundedRect(shadow, radius, radius)

        painter.setPen(QPen(border, 1.0))
        painter.setBrush(QBrush(base))
        painter.drawRoundedRect(rect, radius, radius)

        glyph_width = max(8.0, min(17.0, rect.width() * 0.55))
        glyph_height = max(7.0, min(14.0, rect.height() * 0.45))
        glyph = QRectF(
            rect.center().x() - glyph_width / 2.0,
            rect.center().y() - glyph_height / 2.0,
            glyph_width,
            glyph_height,
        )
        outline = _color("#B7C1CF" if active else "#929EAF", 245)
        painter.setPen(QPen(outline, 1.0))
        painter.setBrush(QBrush(_color("#10141B", 185)))
        painter.drawRoundedRect(glyph, 1.8, 1.8)

        inner = glyph.adjusted(2.0, 2.0, -2.0, -2.0)
        zone = QRectF(inner)
        thickness_x = max(2.0, inner.width() * 0.34)
        thickness_y = max(2.0, inner.height() * 0.36)
        if direction == "left":
            zone.setWidth(thickness_x)
        elif direction == "right":
            zone.setLeft(inner.right() - thickness_x)
        elif direction == "up":
            zone.setHeight(thickness_y)
        elif direction == "down":
            zone.setTop(inner.bottom() - thickness_y)

        fill = QColor(accent)
        fill.setAlpha(205 if active else 170)
        painter.setPen(QPen(fill, 0.7))
        painter.setBrush(QBrush(fill))
        painter.drawRoundedRect(zone, 1.0, 1.0)

    def _is_close_button(self, button, title):
        if not self._compact_title_button(button, title):
            return False

        labels = []
        for accessor in (
            "objectName",
            "text",
            "toolTip",
            "statusTip",
            "whatsThis",
            "accessibleName",
            "accessibleDescription",
        ):
            try:
                labels.append(str(getattr(button, accessor)()))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        try:
            action = button.defaultAction()
            if action is not None:
                labels.extend((str(action.objectName()), str(action.text()), str(action.toolTip())))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

        identity = " ".join(labels).strip().casefold()
        if any(token in identity for token in ("close", "dismiss", "\u5173\u95ed", "\u95dc\u9589")):
            return True
        if any(label.strip().casefold() in {"x", "\u00d7", "\u2715", "\u2716"} for label in labels):
            return True

        # Several native dock titles expose icon-only actions with no semantic
        # text.  Across the built-in title layout the close action is the
        # rightmost compact button; keep the inference local to that title so
        # ordinary plugin buttons and tab controls retain their native painter.
        return self._is_rightmost_title_button(button, title)

    @staticmethod
    def _compact_title_button(button, title):
        try:
            limit = max(48, int(title.height() * 2.2))
            return 0 < button.width() <= limit and 0 < button.height() <= limit
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    @staticmethod
    def _is_floating_title(title):
        current = title
        while current is not None:
            names = set(_meta_class_names(current))
            if (
                "DockAreaDragTitle" in names
                or "TopLevelDockArea" in names
                or any("FloatingDock" in name for name in names)
            ):
                return True
            try:
                if current.isWindow() and names.intersection(
                    {
                        "DockArea",
                        "DockWidget",
                        "IDADockWidget",
                        "BaseDockWidget",
                        "ComplexDockWidget",
                    }
                ):
                    return True
                current = current.parentWidget()
            except (AttributeError, RuntimeError):
                return False
        return False

    def _is_rightmost_title_button(self, button, title):
        candidates = []
        try:
            descendants = title.findChildren(QAbstractButton)
        except (AttributeError, RuntimeError, TypeError):
            descendants = []
        for candidate in descendants:
            try:
                if (
                    candidate.isVisible()
                    and same_qobject(_nearest_title(candidate), title)
                    and self._compact_title_button(candidate, title)
                ):
                    center = _global_center(candidate)
                    if center is not None:
                        candidates.append((center.x(), candidate))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        if not candidates:
            return False
        rightmost = max(candidates, key=lambda item: item[0])[1]
        return same_qobject(rightmost, button)

    def _is_title_action_button(self, button, title):
        """Match only native multi-action dock title strips.

        A few host builds expose the title controls as anonymous buttons.  A
        title with at least two visible compact buttons is the stable shape of
        that native strip; single-button plugin headers retain their own paint
        path.
        """
        if not self._compact_title_button(button, title):
            return False
        try:
            descendants = title.findChildren(QAbstractButton)
        except (AttributeError, RuntimeError, TypeError):
            return False
        candidates = []
        for candidate in descendants:
            try:
                if (
                    candidate.isVisible()
                    and same_qobject(_nearest_title(candidate), title)
                    and self._compact_title_button(candidate, title)
                ):
                    candidates.append(candidate)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        return len(candidates) >= 2

    def _title_button_rank(self, button, title):
        """Return the left-to-right rank among visible native title buttons."""
        candidates = []
        try:
            descendants = title.findChildren(QAbstractButton)
        except (AttributeError, RuntimeError, TypeError):
            descendants = []
        for candidate in descendants:
            try:
                if (
                    candidate.isVisible()
                    and same_qobject(_nearest_title(candidate), title)
                    and self._compact_title_button(candidate, title)
                ):
                    center = _global_center(candidate)
                    if center is not None:
                        candidates.append((center.x(), candidate))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        candidates.sort(key=lambda item: item[0])
        for index, (_x, candidate) in enumerate(candidates):
            if same_qobject(candidate, button):
                return index, len(candidates)
        return -1, len(candidates)

    def _paint_close_button(self, button, title):
        painter = self._new_painter(button)
        if painter is None:
            return False
        try:
            active_title = False
            if title is not None:
                try:
                    active_title = bool(title.property("active"))
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
            # Keep the custom-painted close button flush with the layered-slate
            # DockWidgetTitle colors from modern_dark.qss.
            title_background = _color("#222A35" if active_title else "#1C222B")
            painter.fillRect(QRectF(button.rect()), title_background)

            hovered = _cursor_inside(button)
            try:
                pressed = bool(button.isDown())
                enabled = bool(button.isEnabled())
            except (AttributeError, RuntimeError):
                pressed = False
                enabled = True

            bounds = QRectF(button.rect())
            inset = max(1.0, min(2.5, min(bounds.width(), bounds.height()) * 0.08))
            face = bounds.adjusted(inset, inset, -inset, -inset)
            if pressed:
                fill = _color("#404958")
            elif hovered:
                fill = _color("#343C49")
            else:
                fill = title_background
            painter.setPen(QPen(_color("#556174", 175) if hovered else fill, 0.8))
            painter.setBrush(QBrush(fill))
            painter.drawRoundedRect(face, min(self.radius, 4.0), min(self.radius, 4.0))

            size = max(5.0, min(9.0, min(face.width(), face.height()) * 0.38))
            center = face.center()
            half = size / 2.0
            foreground = _color("#DCE3EC" if enabled else "#788291")
            pen = QPen(foreground, 1.45)
            pen.setCapStyle(_enum(Qt, "PenCapStyle", "RoundCap"))
            painter.setPen(pen)
            painter.drawLine(
                QPointF(center.x() - half, center.y() - half),
                QPointF(center.x() + half, center.y() + half),
            )
            painter.drawLine(
                QPointF(center.x() + half, center.y() - half),
                QPointF(center.x() - half, center.y() + half),
            )
            return True
        finally:
            painter.end()

    def _paint_title_action(self, button, title):
        """Paint the two anonymous dock actions with a quiet modern glyph."""
        rank, count = self._title_button_rank(button, title)
        if rank < 0 or count < 2:
            return False
        # The rightmost action is always the close control; share its exact
        # hover/pressed treatment with the semantic close path.
        if rank == count - 1:
            return self._paint_close_button(button, title)

        painter = self._new_painter(button)
        if painter is None:
            return False
        try:
            active_title = False
            if title is not None:
                try:
                    active_title = bool(title.property("active"))
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
            title_background = _color("#222A35" if active_title else "#1C222B")
            painter.fillRect(QRectF(button.rect()), title_background)

            hovered = _cursor_inside(button)
            try:
                pressed = bool(button.isDown())
                enabled = bool(button.isEnabled())
            except (AttributeError, RuntimeError):
                pressed = False
                enabled = True
            bounds = QRectF(button.rect())
            inset = max(1.0, min(2.5, min(bounds.width(), bounds.height()) * 0.08))
            face = bounds.adjusted(inset, inset, -inset, -inset)
            if pressed:
                fill = _color("#404958")
            elif hovered:
                fill = _color("#343C49")
            else:
                fill = title_background
            painter.setPen(QPen(_color("#556174", 175) if hovered else fill, 0.8))
            painter.setBrush(QBrush(fill))
            painter.drawRoundedRect(face, min(self.radius, 4.0), min(self.radius, 4.0))

            foreground = _color(
                "#DCE3EC" if hovered and enabled else "#9AA6B8" if enabled else "#687486"
            )
            pen = QPen(foreground, 1.2)
            pen.setCapStyle(_enum(Qt, "PenCapStyle", "RoundCap"))
            pen.setJoinStyle(_enum(Qt, "PenJoinStyle", "RoundJoin"))
            painter.setPen(pen)
            painter.setBrush(QBrush(_color("#10141B", 45)))
            center = face.center()
            if rank == 0:
                glyph = QRectF(center.x() - 4.0, center.y() - 4.0, 8.0, 8.0)
                painter.drawRoundedRect(glyph, 1.1, 1.1)
            else:
                back = QRectF(center.x() - 4.5, center.y() - 3.0, 7.0, 7.0)
                front = QRectF(center.x() - 1.5, center.y() - 1.0, 7.0, 7.0)
                painter.drawRoundedRect(back, 1.0, 1.0)
                painter.drawRoundedRect(front, 1.0, 1.0)
            return True
        finally:
            painter.end()


def apply_dock_runtime(accent="#82AAFF", radius=4, force_scan=False):
    """Enable local painters and optionally run one explicit inventory scan."""
    global _runtime_controller

    app = QApplication.instance()
    if app is None:
        return
    if _runtime_controller is not None:
        try:
            same_app = _runtime_controller.parent() is app
        except (AttributeError, RuntimeError):
            same_app = False
        if not same_app:
            _runtime_controller.deactivate()
            _runtime_controller = None
    if _runtime_controller is None:
        _runtime_controller = _DockRuntimeController(app)

    first_activation = not _runtime_controller.enabled
    _runtime_controller.configure(accent, radius)
    if first_activation or bool(force_scan):
        _runtime_controller.discover_existing(app)
    else:
        _runtime_controller.update_targets()


def rescan_dock_runtime():
    """Perform the ready-to-run inventory scan once when explicitly requested."""
    app = QApplication.instance()
    if (
        app is None
        or _runtime_controller is None
        or not _runtime_controller.enabled
    ):
        return dock_runtime_diagnostics()
    _runtime_controller.discover_existing(app)
    return _runtime_controller.diagnostics()


def dock_runtime_diagnostics():
    """Return runtime counters without scanning QApplication or widget trees."""
    if _runtime_controller is None:
        return {
            "enabled": False,
            "scan_count": 0,
            "target_counts": {
                _ROLE_ARROW: 0,
                _ROLE_ARROW_AREA: 0,
                _ROLE_CLOSE: 0,
            },
        }
    return _runtime_controller.diagnostics()


def refresh_dock_runtime(widget):
    """Discover targets around one widget from IDA's widget-visible hook."""
    if _runtime_controller is None or not _runtime_controller.enabled:
        return
    _runtime_controller.refresh(widget)


def restore_dock_runtime():
    """Remove local filters and restore guide background attributes."""
    if _runtime_controller is None:
        return
    _runtime_controller.deactivate()


__all__ = [
    "apply_dock_runtime",
    "dock_runtime_diagnostics",
    "refresh_dock_runtime",
    "rescan_dock_runtime",
    "restore_dock_runtime",
]
