#!/usr/bin/env python3
"""Static and optional offscreen checks for Functions row rounding."""

from __future__ import annotations

import gc
import os
import py_compile
import sys
import warnings
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "ida_modern_ui" / "selection_runtime.py"
QSS = ROOT / "src" / "ida_modern_ui" / "themes" / "modern_dark.qss"


def static_checks() -> None:
    raw = SOURCE.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SystemExit("SELECTION_RUNTIME_FAILED: UTF-8 BOM")
    text = raw.decode("utf-8")
    required = (
        "functions_dirtree_widget_t",
        "names_dirtree_widget_t",
        "tchooser_table_widget_t",
        "chooser_widget_t",
        "QPaintEvent",
        "selectedRows",
        "visualRect",
        "modernUiPluginPanel",
        "QObject.disconnect",
        "_disconnect_connections",
        "_SelectionHostRelay",
        "ChildAdded",
        "QTimer.singleShot",
        "shiboken6.isValid",
        "pending_host_count",
        "target_host_count",
        "_LOCAL_STYLE_BEGIN",
        "_NAMES_HIGHLIGHT_COLORS",
        "_apply_names_highlight_properties",
        "qproperty-highlight_bg_default",
        "qproperty-highlight_bg_selected",
        "apply_selection_runtime",
        "restore_selection_runtime",
    )
    missing = [token for token in required if token not in text]
    if missing:
        raise SystemExit("SELECTION_RUNTIME_FAILED: missing " + ", ".join(missing))
    if "QApplication.instance().installEventFilter" in text:
        raise SystemExit("SELECTION_RUNTIME_FAILED: application-wide event filter")
    qss = QSS.read_text(encoding="utf-8")
    if "functions_dirtree_widget_t::item:selected:first" in qss:
        raise SystemExit("SELECTION_RUNTIME_FAILED: cell-level first radius remains")
    if "functions_dirtree_widget_t::item:selected:last" in qss:
        raise SystemExit("SELECTION_RUNTIME_FAILED: cell-level last radius remains")
    for token in (
        "qproperty-highlight_bg_default",
        "qproperty-highlight_bg_selected",
    ):
        if token not in qss:
            raise SystemExit("SELECTION_RUNTIME_FAILED: missing QSS token " + token)
    if "qproperty-highlight-bg-" in qss:
        raise SystemExit("SELECTION_RUNTIME_FAILED: malformed QSS qproperty name")
    py_compile.compile(str(SOURCE), doraise=True)


def qt_smoke() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from PySide6.QtCore import QCoreApplication, QEvent, QItemSelectionModel, QObject, Property
        from PySide6.QtGui import QColor, QPalette, QStandardItem, QStandardItemModel
        from PySide6.QtWidgets import QApplication, QSplitter, QTableView, QTreeView, QWidget
    except ImportError:
        try:
            from PyQt5.QtCore import (
                QCoreApplication,
                QEvent,
                QItemSelectionModel,
                QObject,
                pyqtProperty as Property,
            )
            from PyQt5.QtGui import QColor, QPalette, QStandardItem, QStandardItemModel
            from PyQt5.QtWidgets import QApplication, QSplitter, QTableView, QTreeView, QWidget
        except ImportError:
            print("SELECTION_RUNTIME_OK static_only=1")
            return

    from ida_modern_ui import selection_runtime as selection_module
    from ida_modern_ui.selection_runtime import (
        apply_selection_runtime,
        restore_selection_runtime,
        selection_runtime_diagnostics,
    )

    class dirtree_left_gutter_fixture_t(QTreeView):
        """Mirror IDA's private dirtree, which leaves x=0..visualRect.left blank."""

        def drawRow(self, painter, option, index):  # noqa: N802 - Qt API
            super().drawRow(painter, option, index)
            selection = self.selectionModel()
            if selection is None or not selection.isRowSelected(index.row(), index.parent()):
                return
            content = self.visualRect(index)
            if content.left() <= self.viewport().rect().left():
                return
            painter.fillRect(
                self.viewport().rect().left(),
                option.rect.top(),
                content.left() - self.viewport().rect().left(),
                option.rect.height(),
                QColor("#0E131A"),
            )

    class functions_dirtree_widget_t(dirtree_left_gutter_fixture_t):
        pass

    class plugin_functions_dirtree_widget_t(functions_dirtree_widget_t):
        pass

    class names_dirtree_widget_t(dirtree_left_gutter_fixture_t):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._highlight_bg_default = QColor("#7A1830")
            self._highlight_bg_selected = QColor("#E45B7A")
            roles = getattr(QPalette, "ColorRole", QPalette)
            highlight = getattr(
                roles, "Highlight", getattr(QPalette, "Highlight", None)
            )
            highlighted_text = getattr(
                roles,
                "HighlightedText",
                getattr(QPalette, "HighlightedText", None),
            )
            palette = QPalette(self.palette())
            palette.setColor(highlight, QColor("#6B3F8C"))
            palette.setColor(highlighted_text, QColor("#C5D4E8"))
            self.setPalette(palette)

        def get_highlight_bg_default(self):
            return QColor(self._highlight_bg_default)

        def set_highlight_bg_default(self, value):
            self._highlight_bg_default = QColor(value)

        def get_highlight_bg_selected(self):
            return QColor(self._highlight_bg_selected)

        def set_highlight_bg_selected(self, value):
            self._highlight_bg_selected = QColor(value)

        highlight_bg_default = Property(
            QColor, get_highlight_bg_default, set_highlight_bg_default
        )
        highlight_bg_selected = Property(
            QColor, get_highlight_bg_selected, set_highlight_bg_selected
        )

    def palette_enum(holder_name, member):
        holder = getattr(QPalette, holder_name, QPalette)
        return getattr(holder, member, getattr(QPalette, member, None))

    def names_palette_colors(view, role_name):
        role = palette_enum("ColorRole", role_name)
        return tuple(
            view.palette().color(palette_enum("ColorGroup", group), role).name().upper()
            for group in ("Active", "Disabled", "Inactive")
        )

    def palette_resolve_mask(palette):
        getter = getattr(palette, "resolveMask", None)
        if callable(getter):
            return int(getter())
        return int(palette.resolve())

    def snapshot_colors(snapshot, role_name):
        role = palette_enum("ColorRole", role_name)
        return tuple(
            snapshot.brushes[(palette_enum("ColorGroup", group), role)]
            .color()
            .name()
            .upper()
            for group in ("Active", "Disabled", "Inactive")
        )

    class chooser_table_widget_t(QTableView):
        pass

    class tchooser_table_widget_t(chooser_table_widget_t):
        pass

    class chooser_widget_t(QWidget):
        pass

    class TChooser(chooser_widget_t):
        pass

    class standalone_dirtree_widget_host_t(QWidget):
        pass

    app = QApplication.instance() or QApplication([])
    deferred_delete = getattr(
        getattr(QEvent, "Type", QEvent),
        "DeferredDelete",
        getattr(QEvent, "DeferredDelete", None),
    )

    def flush_deletes() -> None:
        if deferred_delete is not None:
            QCoreApplication.sendPostedEvents(None, deferred_delete)
        app.processEvents()

    def grab_viewport(view):
        """Return a viewport image plus its logical-to-device scale."""

        pixmap = view.viewport().grab()
        try:
            scale = float(pixmap.devicePixelRatioF())
        except AttributeError:  # Qt 5 bindings expose only the integer API.
            scale = float(pixmap.devicePixelRatio())
        return pixmap.toImage(), max(1.0, scale)

    def logical_pixel(image, scale, x, y):
        """Sample a Qt logical coordinate from a DPR-scaled grab."""

        device_x = max(0, min(image.width() - 1, int(round(float(x) * scale))))
        device_y = max(0, min(image.height() - 1, int(round(float(y) * scale))))
        return image.pixelColor(device_x, device_y)

    def selected_row_fill(image, scale, view, index):
        """Find the dominant interior color without assuming platform font metrics."""

        colors = []
        model = view.model()
        parent = index.parent()
        for column in range(model.columnCount(parent)):
            rect = view.visualRect(model.index(index.row(), column, parent))
            if not rect.isValid():
                continue
            left = max(0, rect.left() + 2)
            right = max(left, rect.right() - 2)
            for y in (
                max(rect.top() + 2, rect.center().y() - 3),
                rect.center().y(),
                min(rect.bottom() - 2, rect.center().y() + 3),
            ):
                colors.extend(
                    logical_pixel(image, scale, x, y).name().upper()
                    for x in range(left, right + 1, 3)
                )
        if not colors:
            raise SystemExit("SELECTION_RUNTIME_FAILED: selected row had no pixels")
        return Counter(colors).most_common(1)[0][0]

    def make_tree(parent=None, rows=3, columns=2):
        candidate = functions_dirtree_widget_t(parent)
        candidate_model = QStandardItemModel(rows, columns, candidate)
        for row in range(rows):
            for column in range(columns):
                candidate_model.setItem(row, column, QStandardItem(f"r{row}c{column}"))
        candidate.setModel(candidate_model)
        candidate.setSelectionBehavior(row_selection)
        candidate.resize(260, 110)
        return candidate

    row_selection = (
        QTreeView.SelectionBehavior.SelectRows
        if hasattr(QTreeView, "SelectionBehavior")
        else QTreeView.SelectRows
    )
    tree = functions_dirtree_widget_t()
    model = QStandardItemModel(4, 3)
    for row in range(4):
        for col in range(3):
            model.setItem(row, col, QStandardItem(f"r{row}c{col}"))
    tree.setModel(model)
    tree.setSelectionBehavior(row_selection)
    tree.resize(300, 140)
    tree.show()

    plugin = plugin_functions_dirtree_widget_t()
    plugin.setProperty("modernUiPluginPanel", True)
    plugin.setModel(model)
    plugin.resize(300, 140)
    plugin.show()
    app.processEvents()
    idx = model.index(1, 0)
    tree.selectionModel().select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
    app.processEvents()

    apply_selection_runtime()
    apply_selection_runtime()
    app.processEvents()
    diag = selection_runtime_diagnostics()
    if diag.get("functions_count") != 1:
        raise SystemExit("SELECTION_RUNTIME_FAILED: target attach count " + str(diag))
    entry = next(iter(selection_module._RUNTIME._entries.values()))
    connection_count = len(entry.connections)
    if connection_count < 4:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: signal handles were not retained "
            + str(connection_count)
        )
    apply_selection_runtime()
    if len(entry.connections) != connection_count:
        raise SystemExit("SELECTION_RUNTIME_FAILED: repeated apply duplicated signals")

    image, image_scale = grab_viewport(tree)
    row_rect = tree.visualRect(idx)
    # The centre remains the native selection colour while the extreme corner
    # is restored to the dark viewport surface.
    center = logical_pixel(
        image, image_scale, max(1, row_rect.left() + 8), row_rect.center().y()
    ).name().upper()
    corner = logical_pixel(
        image, image_scale, max(0, row_rect.left()), max(0, row_rect.top())
    ).name().upper()
    gutter_points = [
        x
        for x in (2, 8, 17)
        if tree.viewport().rect().left() <= x < row_rect.left()
    ]
    gutter_colors = [
        logical_pixel(image, image_scale, x, row_rect.center().y()).name().upper()
        for x in gutter_points
    ]
    if center in {"#111318", "#000000"}:
        raise SystemExit("SELECTION_RUNTIME_FAILED: native selection was erased")
    if not gutter_colors or any(color != center for color in gutter_colors):
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: Functions left gutter discontinuity "
            + str(list(zip(gutter_points, gutter_colors)))
            + " center="
            + center
        )
    if corner not in {"#111318", "#101319", "#0F141B", "#000000"}:
        # Palette differences are acceptable, but a selected fill at the exact
        # corner indicates that the mask did not run at all.
        if corner == center:
            raise SystemExit("SELECTION_RUNTIME_FAILED: corner mask not applied")

    # Model/view teardown can remove connections before the theme restores.
    # Disconnecting their retained handles again must be silent and idempotent.
    for _signal, _callback, handle in tuple(entry.connections):
        if handle is not None:
            QObject.disconnect(handle)
    with warnings.catch_warnings(record=True) as teardown_warnings:
        warnings.simplefilter("always", RuntimeWarning)
        restore_selection_runtime()
        restore_selection_runtime()
        app.processEvents()
    if teardown_warnings:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: repeated teardown warned "
            + str([str(item.message) for item in teardown_warnings])
        )
    if selection_runtime_diagnostics().get("functions_count"):
        raise SystemExit("SELECTION_RUNTIME_FAILED: restore leaked entries")

    # Names and Strings use different native view classes but require the same
    # whole-row silhouette. Their host-local relays must be registered without
    # broadening the scope to unrelated choosers or plugin-owned panels.
    selection_scope = QWidget()
    names_host = standalone_dirtree_widget_host_t(selection_scope)
    names_host.setWindowTitle("Names")
    names_view = names_dirtree_widget_t(names_host)
    names_model = QStandardItemModel(4, 3, names_view)
    for row in range(4):
        for column in range(3):
            names_model.setItem(row, column, QStandardItem(f"n{row}c{column}"))
    names_view.setModel(names_model)
    names_view.setSelectionBehavior(row_selection)
    names_view.resize(300, 140)

    strings_host = TChooser(selection_scope)
    strings_host.setObjectName("Strings")
    strings_host.setWindowTitle("Strings")
    strings_splitter = QSplitter(strings_host)
    strings_splitter.setObjectName("Strings_splitter")
    strings_view = tchooser_table_widget_t(strings_splitter)
    strings_view.setObjectName("Strings")
    strings_model = QStandardItemModel(4, 3, strings_view)
    for row in range(4):
        for column in range(3):
            strings_model.setItem(row, column, QStandardItem(f"s{row}c{column}"))
    strings_view.setModel(strings_model)
    strings_view.setSelectionBehavior(row_selection)
    strings_view.resize(300, 140)

    unrelated_host = TChooser(selection_scope)
    unrelated_host.setObjectName("Imports")
    unrelated_splitter = QSplitter(unrelated_host)
    unrelated_splitter.setObjectName("Imports_splitter")
    unrelated_view = tchooser_table_widget_t(unrelated_splitter)
    unrelated_view.setObjectName("Imports")
    unrelated_view.setModel(QStandardItemModel(2, 2, unrelated_view))

    plugin_host = TChooser(selection_scope)
    plugin_host.setObjectName("Strings")
    plugin_host.setProperty("modernUiPluginPanel", True)
    plugin_splitter = QSplitter(plugin_host)
    plugin_splitter.setObjectName("Strings_splitter")
    plugin_view = tchooser_table_widget_t(plugin_splitter)
    plugin_view.setObjectName("Strings")
    plugin_view.setModel(QStandardItemModel(2, 2, plugin_view))

    selection_scope.resize(680, 360)
    names_host.resize(320, 160)
    strings_host.resize(320, 160)
    strings_host.move(330, 0)
    strings_splitter.resize(320, 160)
    unrelated_host.resize(320, 160)
    unrelated_host.move(0, 180)
    unrelated_splitter.resize(320, 160)
    plugin_host.resize(320, 160)
    plugin_host.move(330, 180)
    plugin_splitter.resize(320, 160)
    for candidate in (
        names_view,
        strings_view,
        unrelated_view,
        plugin_view,
        strings_splitter,
        unrelated_splitter,
        plugin_splitter,
        names_host,
        strings_host,
        unrelated_host,
        plugin_host,
        selection_scope,
    ):
        candidate.show()
    app.processEvents()

    names_index = names_model.index(1, 0)
    strings_index = strings_model.index(1, 0)
    names_view.selectionModel().select(
        names_index, QItemSelectionModel.Select | QItemSelectionModel.Rows
    )
    strings_view.selectionModel().select(
        strings_index, QItemSelectionModel.Select | QItemSelectionModel.Rows
    )
    apply_selection_runtime(selection_scope)
    app.processEvents()
    expanded = selection_runtime_diagnostics()
    expected_counts = {
        "functions_count": 0,
        "names_count": 1,
        "strings_count": 1,
        "target_count": 2,
        "host_count": 0,
        "target_host_count": 3,
    }
    if any(expanded.get(name) != value for name, value in expected_counts.items()):
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: expanded target inventory " + str(expanded)
        )
    kinds = {entry.kind for entry in selection_module._RUNTIME._entries.values()}
    if kinds != {"names", "strings"}:
        raise SystemExit("SELECTION_RUNTIME_FAILED: wrong expanded kinds " + str(kinds))
    if selection_module._target_kind(unrelated_view) is not None:
        raise SystemExit("SELECTION_RUNTIME_FAILED: unrelated chooser was targeted")
    if selection_module._target_kind(plugin_view) is not None:
        raise SystemExit("SELECTION_RUNTIME_FAILED: plugin chooser was targeted")
    if names_view.styleSheet().count(selection_module._LOCAL_STYLE_BEGIN) != 1:
        raise SystemExit("SELECTION_RUNTIME_FAILED: Names decoration style missing")
    names_property_colors = {
        name: names_view.property(name).name().upper()
        for name in ("highlight_bg_default", "highlight_bg_selected")
    }
    if names_property_colors != {
        "highlight_bg_default": "#0F141B",
        "highlight_bg_selected": "#31405A",
    }:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: Names qproperty colours "
            + str(names_property_colors)
        )
    if names_palette_colors(names_view, "Highlight") != ("#31405A",) * 3:
        raise SystemExit("SELECTION_RUNTIME_FAILED: Names palette bridge missing")
    if names_palette_colors(names_view, "HighlightedText") != ("#F0F4FA",) * 3:
        raise SystemExit("SELECTION_RUNTIME_FAILED: Names text palette bridge missing")
    if names_palette_colors(names_view.viewport(), "Highlight") != ("#31405A",) * 3:
        raise SystemExit("SELECTION_RUNTIME_FAILED: Names viewport palette bridge missing")
    if names_palette_colors(names_view.viewport(), "HighlightedText") != (
        "#F0F4FA",
    ) * 3:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: Names viewport text palette bridge missing"
        )
    if (
        selection_module._selected_color(names_view, names_view.viewport())
        .name()
        .upper()
        != "#31405A"
    ):
        raise SystemExit("SELECTION_RUNTIME_FAILED: Names bridge colour diverged")
    apply_selection_runtime(selection_scope)
    if names_view.styleSheet().count(selection_module._LOCAL_STYLE_BEGIN) != 1:
        raise SystemExit("SELECTION_RUNTIME_FAILED: Names decoration style duplicated")

    for label, view, index in (
        ("Names", names_view, names_index),
        ("Strings", strings_view, strings_index),
    ):
        image, image_scale = grab_viewport(view)
        rect = view.visualRect(index)
        row_fill = selected_row_fill(image, image_scale, view, index)
        corner = logical_pixel(
            image, image_scale, max(0, rect.left()), max(0, rect.top())
        ).name().upper()
        if row_fill == corner:
            raise SystemExit(
                f"SELECTION_RUNTIME_FAILED: {label} outer corner was not masked"
            )
        if label == "Names":
            if row_fill != "#31405A":
                raise SystemExit(
                    "SELECTION_RUNTIME_FAILED: Names selected row fill " + row_fill
                )
            gutter_points = [x for x in (2, 8, 17) if x < rect.left()]
            gutter_colors = [
                logical_pixel(image, image_scale, x, rect.center().y()).name().upper()
                for x in gutter_points
            ]
            if not gutter_colors or any(color != row_fill for color in gutter_colors):
                raise SystemExit(
                    "SELECTION_RUNTIME_FAILED: Names left gutter discontinuity "
                    + str(list(zip(gutter_points, gutter_colors)))
                    + " fill="
                    + row_fill
                )

    # Move focus away from Names and sample only decoration/cell boundaries,
    # where no glyph can legitimately interrupt the continuous row fill.
    strings_view.setFocus()
    names_view.clearFocus()
    app.processEvents()
    inactive_image, inactive_scale = grab_viewport(names_view)
    inactive_y = names_view.visualRect(names_index).center().y()
    inactive_points = []
    first_rect = names_view.visualRect(names_model.index(1, 0))
    inactive_points.extend(x for x in (2, 8, 17) if x < first_rect.left())
    inactive_points.append(max(0, first_rect.left() - 1))
    for column in range(1, names_model.columnCount()):
        boundary = names_view.visualRect(names_model.index(1, column)).left()
        inactive_points.extend((max(0, boundary - 1), max(0, boundary)))
    inactive_colors = [
        logical_pixel(inactive_image, inactive_scale, x, inactive_y).name().upper()
        for x in inactive_points
    ]
    if not inactive_colors or any(color != "#31405A" for color in inactive_colors):
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: inactive Names row discontinuity "
            + str(list(zip(inactive_points, inactive_colors)))
        )

    names_view.deleteLater()
    strings_view.deleteLater()
    flush_deletes()
    destroyed_expanded = selection_runtime_diagnostics()
    if (
        destroyed_expanded.get("target_count") != 0
        or destroyed_expanded.get("target_host_count") != 3
    ):
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: expanded child cleanup "
            + str(destroyed_expanded)
        )

    names_view = names_dirtree_widget_t(names_host)
    names_view.setModel(QStandardItemModel(2, 2, names_view))
    names_view.setSelectionBehavior(row_selection)
    names_view.resize(300, 140)
    strings_view = tchooser_table_widget_t(strings_splitter)
    strings_view.setObjectName("Strings")
    strings_view.setModel(QStandardItemModel(2, 2, strings_view))
    strings_view.setSelectionBehavior(row_selection)
    strings_view.resize(300, 140)
    names_view.show()
    strings_view.show()
    app.processEvents()
    rebuilt_expanded = selection_runtime_diagnostics()
    if (
        rebuilt_expanded.get("names_count") != 1
        or rebuilt_expanded.get("strings_count") != 1
        or rebuilt_expanded.get("target_count") != 2
        or rebuilt_expanded.get("pending_host_count") != 0
    ):
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: expanded relay rebuild "
            + str(rebuilt_expanded)
        )
    if names_view.styleSheet().count(selection_module._LOCAL_STYLE_BEGIN) != 1:
        raise SystemExit("SELECTION_RUNTIME_FAILED: rebuilt Names style missing")
    rebuilt_property_colors = {
        name: names_view.property(name).name().upper()
        for name in ("highlight_bg_default", "highlight_bg_selected")
    }
    if rebuilt_property_colors != {
        "highlight_bg_default": "#0F141B",
        "highlight_bg_selected": "#31405A",
    }:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: rebuilt Names qproperty colours "
            + str(rebuilt_property_colors)
        )
    if names_palette_colors(names_view, "Highlight") != ("#31405A",) * 3:
        raise SystemExit("SELECTION_RUNTIME_FAILED: rebuilt Names palette bridge missing")
    if names_palette_colors(names_view, "HighlightedText") != ("#F0F4FA",) * 3:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: rebuilt Names text palette bridge missing"
        )
    if names_palette_colors(names_view.viewport(), "Highlight") != ("#31405A",) * 3:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: rebuilt Names viewport palette bridge missing"
        )
    if names_palette_colors(names_view.viewport(), "HighlightedText") != (
        "#F0F4FA",
    ) * 3:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: rebuilt Names viewport text palette bridge missing"
        )

    names_entry = next(
        entry
        for entry in selection_module._RUNTIME._entries.values()
        if entry.tree is names_view
    )
    palette_snapshot = names_entry.palette_snapshot
    viewport_palette_snapshot = names_entry.viewport_palette_snapshot
    if palette_snapshot is None or viewport_palette_snapshot is None:
        raise SystemExit("SELECTION_RUNTIME_FAILED: Names palette snapshots missing")
    external_palette = QPalette(names_view.palette())
    window_role = palette_enum("ColorRole", "Window")
    external_palette.setColor(window_role, QColor("#ABCDEF"))
    names_view.setPalette(external_palette)
    external_non_owned_mask = (
        palette_resolve_mask(names_view.palette()) & ~palette_snapshot.owned_mask
    )
    external_viewport_palette = QPalette(names_view.viewport().palette())
    external_viewport_palette.setColor(window_role, QColor("#FEDCBA"))
    names_view.viewport().setPalette(external_viewport_palette)
    external_viewport_non_owned_mask = (
        palette_resolve_mask(names_view.viewport().palette())
        & ~viewport_palette_snapshot.owned_mask
    )

    restore_selection_runtime()
    flush_deletes()
    if selection_module._LOCAL_STYLE_BEGIN in names_view.styleSheet():
        raise SystemExit("SELECTION_RUNTIME_FAILED: Names local style leaked on restore")
    restored_property_colors = {
        name: names_view.property(name).name().upper()
        for name in ("highlight_bg_default", "highlight_bg_selected")
    }
    if restored_property_colors != {
        "highlight_bg_default": "#7A1830",
        "highlight_bg_selected": "#E45B7A",
    }:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: Names qproperty rollback "
            + str(restored_property_colors)
        )
    if names_palette_colors(names_view, "Highlight") != ("#6B3F8C",) * 3:
        raise SystemExit("SELECTION_RUNTIME_FAILED: Names palette rollback missing")
    if names_palette_colors(names_view, "HighlightedText") != ("#C5D4E8",) * 3:
        raise SystemExit("SELECTION_RUNTIME_FAILED: Names text palette rollback missing")
    restored_viewport_highlight = names_palette_colors(
        names_view.viewport(), "Highlight"
    )
    if restored_viewport_highlight != snapshot_colors(
        viewport_palette_snapshot, "Highlight"
    ):
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: Names viewport palette rollback missing "
            + str(restored_viewport_highlight)
        )
    restored_viewport_text = names_palette_colors(
        names_view.viewport(), "HighlightedText"
    )
    if restored_viewport_text != snapshot_colors(
        viewport_palette_snapshot, "HighlightedText"
    ):
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: Names viewport text palette rollback missing "
            + str(restored_viewport_text)
        )
    restored_window_colors = names_palette_colors(names_view, "Window")
    if restored_window_colors != ("#ABCDEF",) * 3:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: unrelated palette role was rolled back "
            + str(restored_window_colors)
        )
    restored_viewport_window_colors = names_palette_colors(
        names_view.viewport(), "Window"
    )
    if restored_viewport_window_colors != ("#FEDCBA",) * 3:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: unrelated viewport palette role was rolled back "
            + str(restored_viewport_window_colors)
        )
    restored_resolve_mask = palette_resolve_mask(names_view.palette())
    restored_non_owned_mask = restored_resolve_mask & ~palette_snapshot.owned_mask
    if restored_non_owned_mask != external_non_owned_mask:
        raise SystemExit("SELECTION_RUNTIME_FAILED: unrelated palette mask was changed")
    if restored_resolve_mask & palette_snapshot.owned_mask != (
        palette_snapshot.resolve_mask & palette_snapshot.owned_mask
    ):
        raise SystemExit("SELECTION_RUNTIME_FAILED: owned palette mask was not restored")
    restored_viewport_resolve_mask = palette_resolve_mask(
        names_view.viewport().palette()
    )
    if (
        restored_viewport_resolve_mask & ~viewport_palette_snapshot.owned_mask
        != external_viewport_non_owned_mask
    ):
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: unrelated viewport palette mask was changed"
        )
    if restored_viewport_resolve_mask & viewport_palette_snapshot.owned_mask != (
        viewport_palette_snapshot.resolve_mask
        & viewport_palette_snapshot.owned_mask
    ):
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: owned viewport palette mask was not restored"
        )
    expanded_clean = selection_runtime_diagnostics()
    if expanded_clean.get("target_count") or expanded_clean.get("target_host_count"):
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: expanded target teardown leaked "
            + str(expanded_clean)
        )
    selection_scope.deleteLater()
    flush_deletes()

    # Exercise the inverse lifetime: the C++ tree/viewport disappear while the
    # runtime still holds their Python wrappers and connection handles.
    doomed = functions_dirtree_widget_t()
    doomed_model = QStandardItemModel(2, 2)
    doomed.setModel(doomed_model)
    doomed.resize(240, 100)
    doomed.show()
    app.processEvents()
    apply_selection_runtime(doomed)
    if selection_runtime_diagnostics().get("functions_count") != 1:
        raise SystemExit("SELECTION_RUNTIME_FAILED: destroyed-object fixture not attached")
    with warnings.catch_warnings(record=True) as destroyed_warnings:
        warnings.simplefilter("always", RuntimeWarning)
        doomed.deleteLater()
        flush_deletes()
        try:
            doomed.viewport()
        except RuntimeError:
            pass
        else:
            raise SystemExit("SELECTION_RUNTIME_FAILED: C++ tree was not destroyed")
        restore_selection_runtime()
        restore_selection_runtime()
        app.processEvents()
    if destroyed_warnings:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: destroyed-object teardown warned "
            + str([str(item.message) for item in destroyed_warnings])
        )
    if selection_runtime_diagnostics().get("functions_count"):
        raise SystemExit("SELECTION_RUNTIME_FAILED: destroyed-object teardown leaked entries")

    # Force a cache-key collision with deleted wrappers. _attach() must reject
    # the stale entry before same_qobject() can accept a recycled C++ address.
    stale_tree = make_tree()
    stale_tree.show()
    app.processEvents()
    stale_viewport = stale_tree.viewport()
    stale_tree.deleteLater()
    flush_deletes()
    if selection_module._is_valid_qobject(stale_tree):
        raise SystemExit("SELECTION_RUNTIME_FAILED: stale wrapper fixture remained valid")
    with warnings.catch_warnings(record=True) as invalid_root_warnings:
        warnings.simplefilter("always", RuntimeWarning)
        apply_selection_runtime(stale_tree)
        restore_selection_runtime()
    if invalid_root_warnings:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: invalid root scan warned "
            + str([str(item.message) for item in invalid_root_warnings])
        )
    replacement = make_tree()
    replacement.show()
    app.processEvents()
    reused_key = selection_module.qobject_key(replacement.viewport())
    stale_filter = selection_module._SelectionPaintFilter(
        stale_tree, stale_viewport, selection_module._RUNTIME
    )
    selection_module._RUNTIME._entries[reused_key] = selection_module._SelectionEntry(
        stale_tree,
        stale_viewport,
        stale_filter,
        [],
        token=object(),
    )
    original_same_qobject = selection_module.same_qobject

    def valid_only_same_qobject(left, right):
        if left is stale_tree or left is stale_viewport:
            raise AssertionError("same_qobject received a deleted wrapper")
        return original_same_qobject(left, right)

    selection_module.same_qobject = valid_only_same_qobject
    try:
        selection_module._RUNTIME.enabled = True
        selection_module._RUNTIME._attach(replacement)
    finally:
        selection_module.same_qobject = original_same_qobject
    reused_entry = selection_module._RUNTIME._entries.get(reused_key)
    if reused_entry is None or reused_entry.tree is not replacement:
        raise SystemExit("SELECTION_RUNTIME_FAILED: recycled key did not replace stale entry")
    restore_selection_runtime()
    flush_deletes()
    replacement.close()

    # Keep one persistent private host and recreate its Functions child fifty
    # times. No apply()/refresh() occurs between child construction and attach:
    # only the host-local ChildAdded relay can discover each replacement.
    host = standalone_dirtree_widget_host_t()
    host.setWindowTitle("Functions")
    host.resize(300, 160)
    host.show()
    app.processEvents()
    lifecycle_warnings = []
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", RuntimeWarning)
        for cycle in range(50):
            apply_selection_runtime(host)
            before = selection_runtime_diagnostics()
            if before.get("host_count") != 1 or before.get("functions_count") != 0:
                raise SystemExit(
                    f"SELECTION_RUNTIME_FAILED: cycle {cycle} host registration " + str(before)
                )
            rebuilt = make_tree(host)
            rebuilt.show()
            app.processEvents()
            attached = selection_runtime_diagnostics()
            if (
                attached.get("host_count") != 1
                or attached.get("functions_count") != 1
                or attached.get("pending_host_count") != 0
            ):
                raise SystemExit(
                    f"SELECTION_RUNTIME_FAILED: cycle {cycle} relay attach " + str(attached)
                )
            live_entry = next(iter(selection_module._RUNTIME._entries.values()))
            if live_entry.tree is not rebuilt:
                raise SystemExit(
                    f"SELECTION_RUNTIME_FAILED: cycle {cycle} attached wrong wrapper"
                )
            rebuilt.deleteLater()
            flush_deletes()
            destroyed = selection_runtime_diagnostics()
            if destroyed.get("functions_count") != 0 or destroyed.get("host_count") != 1:
                raise SystemExit(
                    f"SELECTION_RUNTIME_FAILED: cycle {cycle} destroy cleanup " + str(destroyed)
                )
            restore_selection_runtime()
            restore_selection_runtime()
            flush_deletes()
            clean = selection_runtime_diagnostics()
            if clean.get("functions_count") or clean.get("host_count"):
                raise SystemExit(
                    f"SELECTION_RUNTIME_FAILED: cycle {cycle} map leak " + str(clean)
                )
            relay_objects = selection_module._RUNTIME.findChildren(
                selection_module._SelectionHostRelay
            )
            paint_objects = selection_module._RUNTIME.findChildren(
                selection_module._SelectionPaintFilter
            )
            if relay_objects or paint_objects:
                raise SystemExit(
                    f"SELECTION_RUNTIME_FAILED: cycle {cycle} QObject leak "
                    f"relay={len(relay_objects)} paint={len(paint_objects)}"
                )
            rebuilt = None
            gc.collect()
        lifecycle_warnings.extend(str(item.message) for item in captured)
    if lifecycle_warnings:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: 50-cycle lifecycle warned " + str(lifecycle_warnings)
        )

    # IDA can invalidate a TWidget's PySide wrapper without destroying the C++
    # host or its installed relay. Preserve that host record through prune,
    # then let a same-key ChildAdded event rebind it to the live wrapper.
    apply_selection_runtime(host)
    host_key, host_entry = next(iter(selection_module._RUNTIME._hosts.items()))
    stale_host_wrapper = QWidget()
    stale_host_wrapper.deleteLater()
    flush_deletes()
    if selection_module._is_valid_qobject(stale_host_wrapper):
        raise SystemExit("SELECTION_RUNTIME_FAILED: host churn fixture remained valid")
    host_entry.host = stale_host_wrapper
    selection_module._RUNTIME._prune()
    if selection_runtime_diagnostics().get("host_count") != 1:
        raise SystemExit("SELECTION_RUNTIME_FAILED: prune discarded wrapper-churn host")
    churn_tree = make_tree(host)
    churn_tree.show()
    app.processEvents()
    churn_diag = selection_runtime_diagnostics()
    rebound = selection_module._RUNTIME._hosts.get(host_key)
    if (
        churn_diag.get("functions_count") != 1
        or churn_diag.get("host_count") != 1
        or rebound is not host_entry
        or rebound.host is not host
    ):
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: same-key host wrapper was not rebound "
            + str(churn_diag)
        )
    churn_tree.deleteLater()
    flush_deletes()
    restore_selection_runtime()
    flush_deletes()

    # A queued scan must become inert after restore, even if its host key is
    # registered again before the zero-delay callback runs.
    apply_selection_runtime(host)
    pending_tree = make_tree(host)
    pending = selection_runtime_diagnostics()
    if pending.get("pending_host_count") != 1:
        raise SystemExit("SELECTION_RUNTIME_FAILED: pending scan was not coalesced " + str(pending))
    restore_selection_runtime()
    apply_selection_runtime(host)
    pending_tree.show()
    app.processEvents()
    after_pending = selection_runtime_diagnostics()
    if after_pending.get("functions_count") != 1 or after_pending.get("host_count") != 1:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: restored pending token mutated runtime "
            + str(after_pending)
        )
    with warnings.catch_warnings(record=True) as host_destroy_warnings:
        warnings.simplefilter("always", RuntimeWarning)
        host.deleteLater()
        flush_deletes()
        flush_deletes()
        restore_selection_runtime()
        flush_deletes()
    if host_destroy_warnings:
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: host destruction warned "
            + str([str(item.message) for item in host_destroy_warnings])
        )
    after_host_destroy = selection_runtime_diagnostics()
    if after_host_destroy.get("functions_count") or after_host_destroy.get("host_count"):
        raise SystemExit(
            "SELECTION_RUNTIME_FAILED: host destruction leaked maps "
            + str(after_host_destroy)
        )
    if selection_module._RUNTIME.findChildren(selection_module._SelectionHostRelay):
        raise SystemExit("SELECTION_RUNTIME_FAILED: host destruction leaked relay QObject")
    if selection_module._RUNTIME.findChildren(selection_module._SelectionPaintFilter):
        raise SystemExit("SELECTION_RUNTIME_FAILED: host destruction leaked paint QObject")

    # A clean cycle after every teardown order confirms handles were reset.
    apply_selection_runtime(tree)
    if selection_runtime_diagnostics().get("functions_count") != 1:
        raise SystemExit("SELECTION_RUNTIME_FAILED: reapply after lifecycle failed")
    restore_selection_runtime()
    flush_deletes()
    tree.close()
    plugin.close()
    print(
        "SELECTION_RUNTIME_OK static=1 qt=1 targets=functions,names,strings relay_rebuild=50 "
        "wrapper_churn=1 recycled_key=1 pending_restore=1 qobject_leak=0 warnings=0"
    )


if __name__ == "__main__":
    static_checks()
    qt_smoke()
