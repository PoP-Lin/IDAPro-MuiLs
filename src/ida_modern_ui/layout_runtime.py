# -*- coding: utf-8 -*-
"""One-time Output/Strings layout polish that then yields to saved desktops."""

from __future__ import annotations

import ida_kernwin

from .qt_compat import (
    QApplication,
    QSplitter,
    horizontal_orientation,
    qobject_key,
    same_qobject,
    vertical_orientation,
)


BASE_LAYOUT_VERSION = 1
TARGET_LAYOUT_VERSION = 2
OUTPUT_PERCENT = 43
STRINGS_PERCENT = 57
THREE_OUTPUT_PERCENT = 32
THREE_STRINGS_PERCENT = 36
THREE_NAMES_PERCENT = 32
FUNCTIONS_PERCENT = 29
EDITOR_PERCENT = 68
LOWER_PERCENT = 32

_diagnostics = {
    "attempt_count": 0,
    "apply_count": 0,
    "horizontal_sizes": [],
    "vertical_sizes": [],
    "top_horizontal_sizes": [],
    "target_widths": [],
    "mode": "none",
    "last_result": "not-attempted",
}

# Built-in chooser/tree column polish is deliberately separate from splitter
# migration.  It runs only at lifecycle boundaries (ready/desktop/widget
# visible), never from resize or paint paths, and is guarded per native header
# object so a user's later manual column adjustment is left untouched.
# Version 2 adds a dedicated three-column Names layout.  Bumping the native
# header marker lets an already-open workspace migrate from the older
# Name/Address-only pass exactly once, while retaining the same idempotent
# lifecycle behavior afterwards.
COLUMN_LAYOUT_VERSION = 2
_COLUMN_MARK_PROPERTY = "modern_ui_builtin_column_layout"
_COLUMN_MARK = f"v{COLUMN_LAYOUT_VERSION}"
_column_diagnostics = {
    "attempt_count": 0,
    "apply_count": 0,
    "strings": [],
    "names": [],
    "functions": [],
    "last_result": "not-attempted",
}


def _qt_widget(*titles):
    for title in titles:
        try:
            twidget = ida_kernwin.find_widget(title)
            if twidget is not None:
                return ida_kernwin.PluginForm.TWidgetToQtPythonWidget(twidget)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
    return None


def _common_splitter(left, right):
    seen = set()
    current = left
    while current is not None:
        if isinstance(current, QSplitter):
            seen.add(qobject_key(current))
        try:
            current = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            current = None

    current = right
    while current is not None:
        if isinstance(current, QSplitter) and qobject_key(current) in seen:
            return current
        try:
            current = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            current = None
    return None


def _direct_child(widget, splitter):
    current = widget
    while current is not None:
        try:
            if same_qobject(current.parentWidget(), splitter):
                return current
            current = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None
    return None


def _outer_vertical_splitter(widget):
    current = widget
    while current is not None:
        try:
            parent = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None, None
        if isinstance(parent, QSplitter):
            try:
                if parent.orientation() == vertical_orientation():
                    return parent, current
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return None, None
        current = parent
    return None, None


def _is_visible(widget):
    try:
        return bool(widget is not None and widget.isVisible())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _lowest_common_horizontal_splitter(widgets):
    if not widgets or any(widget is None for widget in widgets):
        return None
    current = widgets[0]
    while current is not None:
        if isinstance(current, QSplitter):
            try:
                horizontal = current.orientation() == horizontal_orientation()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                horizontal = False
            if horizontal and all(
                _direct_child(widget, current) is not None for widget in widgets
            ):
                return current
        try:
            current = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            current = None
    return None


def _weighted_horizontal_plan(widgets, weights):
    """Build an inner-first splitter plan without changing live geometry."""
    if len(widgets) != len(weights) or len(widgets) < 2:
        return None, None
    splitter = _lowest_common_horizontal_splitter(widgets)
    if splitter is None:
        return None, None
    try:
        count = int(splitter.count())
        branches = {}
        for widget, weight in zip(widgets, weights):
            child = _direct_child(widget, splitter)
            index = int(splitter.indexOf(child)) if child is not None else -1
            if index < 0:
                return None, splitter
            numeric_weight = int(weight)
            if numeric_weight <= 0:
                return None, splitter
            branches.setdefault(index, []).append((widget, numeric_weight))
        # Do not move unrelated dock branches.  Every direct branch of this
        # splitter must contain at least one of the requested lower panels.
        if len(branches) < 2 or set(branches) != set(range(count)):
            return None, splitter

        # Validate every nested split before returning any work to the caller.
        # Plans are inner-first so their relative leaf weights survive the
        # later resize of the containing outer branch.
        plans = []
        for group in branches.values():
            if len(group) <= 1:
                continue
            nested_plans, _nested = _weighted_horizontal_plan(
                [item[0] for item in group],
                [item[1] for item in group],
            )
            if nested_plans is None:
                return None, splitter
            plans.extend(nested_plans)

        sizes = [int(value) for value in splitter.sizes()]
        if len(sizes) != count:
            return None, splitter
        total = sum(sizes)
        if total < 100:
            return None, splitter
        branch_weights = [
            sum(weight for _widget, weight in branches[index])
            for index in range(count)
        ]
        weight_total = sum(branch_weights)
        if weight_total <= 0:
            return None, splitter
        target = [
            max(1, round(total * weight / weight_total))
            for weight in branch_weights
        ]
        target[-1] = max(1, target[-1] + total - sum(target))
        plans.append((splitter, target))
        return plans, splitter
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None, splitter


def _two_way_ratio_plan(splitter, first, second, first_percent):
    """Return a validated splitter target without mutating the splitter."""
    if splitter is None or first is None or second is None:
        return None
    try:
        if splitter.count() != 2:
            return None
        first_index = splitter.indexOf(first)
        second_index = splitter.indexOf(second)
        if {first_index, second_index} != {0, 1}:
            return None
        sizes = [int(value) for value in splitter.sizes()]
        if len(sizes) != 2:
            return None
        total = sum(sizes)
        if total < 100:
            return None
        first_size = max(1, round(total * float(first_percent) / 100.0))
        target = [0, 0]
        target[first_index] = first_size
        target[second_index] = max(1, total - first_size)
        return splitter, target
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _process_layout_events():
    app = QApplication.instance()
    if app is None:
        return
    try:
        app.processEvents()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def _percentages_within(values, weights, tolerance=2.0):
    try:
        numeric_values = [float(value) for value in values]
        numeric_weights = [float(weight) for weight in weights]
        total = sum(numeric_values)
        weight_total = sum(numeric_weights)
        if (
            len(numeric_values) != len(numeric_weights)
            or not numeric_values
            or total <= 0
            or weight_total <= 0
        ):
            return False
        return all(
            abs(
                (value * 100.0 / total)
                - (weight * 100.0 / weight_total)
            )
            <= float(tolerance)
            for value, weight in zip(numeric_values, numeric_weights)
        )
    except (ArithmeticError, TypeError, ValueError):
        return False


def _widget_widths_match(widgets, weights):
    try:
        widths = [int(widget.width()) for widget in widgets]
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    return _percentages_within(widths, weights)


def _splitter_plan_matches(plan):
    if plan is None:
        return False
    splitter, target = plan
    try:
        actual = [int(value) for value in splitter.sizes()]
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    return _percentages_within(actual, target)


def _commit_splitter_plans(plans, validator=None):
    """Apply plans atomically, restoring every size if commit/validation fails."""
    if not plans:
        return False
    snapshots = []
    seen = set()
    committed = False
    try:
        for splitter, target in plans:
            key = qobject_key(splitter)
            if key in seen:
                return False
            seen.add(key)
            current = [int(value) for value in splitter.sizes()]
            if len(current) != len(target) or sum(current) < 100:
                return False
            snapshots.append((splitter, current))
        for splitter, target in plans:
            splitter.setSizes([int(value) for value in target])
        _process_layout_events()
        committed = validator is None or bool(validator())
    except (ArithmeticError, AttributeError, RuntimeError, TypeError, ValueError):
        committed = False
    if not committed:
        for splitter, sizes in reversed(snapshots):
            try:
                splitter.setSizes(sizes)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        _process_layout_events()
    return committed


def _apply_weighted_horizontal(widgets, weights):
    """Balance target leaves through either flat or nested horizontal splits."""
    plans, splitter = _weighted_horizontal_plan(widgets, weights)
    return _commit_splitter_plans(plans), splitter


def _apply_two_way_ratio(splitter, first, second, first_percent):
    plan = _two_way_ratio_plan(splitter, first, second, first_percent)
    return _commit_splitter_plans([plan] if plan is not None else None)


def _top_workspace_ratio_plan():
    functions = _qt_widget("Functions window", "Functions")
    editor = _qt_widget("IDA View-A")
    if not (_is_visible(functions) and _is_visible(editor)):
        return None, None
    splitter = _common_splitter(functions, editor)
    if splitter is None:
        return None, None
    try:
        if splitter.orientation() != horizontal_orientation():
            return None, splitter
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None, splitter
    plan = _two_way_ratio_plan(
        splitter,
        _direct_child(functions, splitter),
        _direct_child(editor, splitter),
        FUNCTIONS_PERCENT,
    )
    return plan, splitter


def _apply_top_workspace_ratio():
    plan, splitter = _top_workspace_ratio_plan()
    return _commit_splitter_plans([plan] if plan is not None else None), splitter


def apply_balanced_panel_layout():
    """Apply 68:32 editor/lower and 43:57 Output/Strings ratios once."""
    _diagnostics["attempt_count"] += 1
    output = _qt_widget("Output window", "Output")
    strings = _qt_widget("Strings window", "Strings")
    if output is None or strings is None:
        _diagnostics["last_result"] = "panels-unavailable"
        return False

    horizontal = _common_splitter(output, strings)
    if horizontal is None:
        _diagnostics["last_result"] = "horizontal-splitter-unavailable"
        return False
    try:
        if horizontal.orientation() != horizontal_orientation():
            _diagnostics["last_result"] = "panels-not-side-by-side"
            return False
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _diagnostics["last_result"] = "horizontal-orientation-error"
        return False

    output_child = _direct_child(output, horizontal)
    strings_child = _direct_child(strings, horizontal)
    vertical, lower_child = _outer_vertical_splitter(horizontal)
    if vertical is None or lower_child is None:
        _diagnostics["last_result"] = "vertical-splitter-unavailable"
        return False
    try:
        lower_index = vertical.indexOf(lower_child)
        if vertical.count() != 2 or lower_index not in (0, 1):
            _diagnostics["last_result"] = "vertical-child-error"
            return False
        upper_child = vertical.widget(1 - lower_index)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _diagnostics["last_result"] = "vertical-child-error"
        return False

    vertical_plan = _two_way_ratio_plan(
        vertical, upper_child, lower_child, EDITOR_PERCENT
    )
    horizontal_plan = _two_way_ratio_plan(
        horizontal, output_child, strings_child, OUTPUT_PERCENT
    )
    if vertical_plan is None or horizontal_plan is None:
        _diagnostics["last_result"] = "ratio-plan-invalid"
        return False
    if not _commit_splitter_plans(
        [vertical_plan, horizontal_plan],
        validator=lambda: all(
            _splitter_plan_matches(plan)
            for plan in (vertical_plan, horizontal_plan)
        ),
    ):
        _diagnostics["last_result"] = "ratio-application-failed"
        return False

    try:
        _diagnostics["horizontal_sizes"] = [int(value) for value in horizontal.sizes()]
        _diagnostics["vertical_sizes"] = [int(value) for value in vertical.sizes()]
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    _diagnostics["apply_count"] += 1
    _diagnostics["mode"] = "output-strings"
    _diagnostics["last_result"] = "applied"
    # The splitter migration is a lifecycle boundary.  A chooser/tree model
    # may finish materializing between ready_to_run and this commit, so make a
    # single local column pass here as well (never from resize/paint paths).
    try:
        apply_builtin_column_layout()
    except (NameError, AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return True


def apply_balanced_three_panel_layout():
    """Apply a one-time 32:36:32 Output/Strings/Names lower workspace."""
    _diagnostics["attempt_count"] += 1
    output = _qt_widget("Output window", "Output")
    strings = _qt_widget("Strings window", "Strings")
    names = _qt_widget("Names window", "Names")
    if not all(_is_visible(widget) for widget in (output, strings, names)):
        _diagnostics["last_result"] = "three-panels-unavailable"
        return False

    horizontal_plans, horizontal = _weighted_horizontal_plan(
        [output, strings, names],
        [THREE_OUTPUT_PERCENT, THREE_STRINGS_PERCENT, THREE_NAMES_PERCENT],
    )
    if horizontal_plans is None or horizontal is None:
        _diagnostics["last_result"] = "three-panel-splitter-unavailable"
        return False

    vertical, lower_child = _outer_vertical_splitter(horizontal)
    if vertical is None or lower_child is None:
        _diagnostics["last_result"] = "vertical-splitter-unavailable"
        return False
    try:
        lower_index = vertical.indexOf(lower_child)
        if vertical.count() != 2 or lower_index not in (0, 1):
            _diagnostics["last_result"] = "vertical-child-error"
            return False
        upper_child = vertical.widget(1 - lower_index)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _diagnostics["last_result"] = "vertical-child-error"
        return False

    vertical_plan = _two_way_ratio_plan(
        vertical, upper_child, lower_child, EDITOR_PERCENT
    )
    if vertical_plan is None:
        _diagnostics["last_result"] = "vertical-ratio-plan-invalid"
        return False

    top_plan, top_splitter = _top_workspace_ratio_plan()
    if top_plan is None or top_splitter is None:
        _diagnostics["last_result"] = "top-ratio-plan-invalid"
        return False

    # Nothing above has touched the desktop.  Commit all nested horizontal,
    # editor/lower, and Functions/editor targets as one transaction.
    if not _commit_splitter_plans(
        list(horizontal_plans) + [vertical_plan, top_plan],
        validator=lambda: (
            _widget_widths_match(
                [output, strings, names],
                [
                    THREE_OUTPUT_PERCENT,
                    THREE_STRINGS_PERCENT,
                    THREE_NAMES_PERCENT,
                ],
            )
            and all(
                _splitter_plan_matches(plan)
                for plan in (
                    *horizontal_plans,
                    vertical_plan,
                    top_plan,
                )
            )
        ),
    ):
        _diagnostics["last_result"] = "ratio-application-failed"
        return False

    try:
        _diagnostics["horizontal_sizes"] = [int(value) for value in horizontal.sizes()]
        _diagnostics["vertical_sizes"] = [int(value) for value in vertical.sizes()]
        _diagnostics["top_horizontal_sizes"] = [
            int(value) for value in top_splitter.sizes()
        ]
        _diagnostics["target_widths"] = [
            int(output.width()),
            int(strings.width()),
            int(names.width()),
        ]
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    _diagnostics["apply_count"] += 1
    _diagnostics["mode"] = "output-strings-names"
    _diagnostics["last_result"] = "applied"
    # Keep the built-in column pass adjacent to the restored splitter geometry
    # so Names/Functions headers that appear slightly later are covered.
    try:
        apply_builtin_column_layout()
    except (NameError, AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return True


# ---------------------------------------------------------------------------
# Built-in chooser/tree column widths


def _column_meta_names(widget):
    names = []
    try:
        meta = widget.metaObject()
        while meta is not None:
            names.append(str(meta.className()))
            meta = meta.superClass()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return names


def _column_inherits(widget, class_name):
    return class_name in set(_column_meta_names(widget))


def _column_object_name(widget):
    try:
        return str(widget.objectName() or "").strip().casefold()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return ""


def _column_window_title(widget):
    try:
        return str(widget.windowTitle() or "").strip().casefold()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return ""


def _column_walk(root):
    """Yield a widget subtree without importing a binding-specific QWidget."""
    if root is None:
        return
    stack = [root]
    seen = set()
    while stack:
        current = stack.pop()
        try:
            key = qobject_key(current)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            key = id(current)
        if key in seen:
            continue
        seen.add(key)
        yield current
        try:
            children = list(current.children())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            children = []
        stack.extend(reversed(children))


def _column_ancestor_has(widget, class_names=(), labels=()):
    classes = set(class_names)
    wanted_labels = {str(value).casefold() for value in labels}
    current = widget
    for _ in range(10):
        if current is None:
            return False
        if classes and classes.intersection(_column_meta_names(current)):
            return True
        if wanted_labels:
            if (
                _column_object_name(current) in wanted_labels
                or _column_window_title(current) in wanted_labels
            ):
                return True
        try:
            current = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
    return False


def _column_under_builtin_lookup(widget, panel):
    """Require identity with IDA's canonical built-in panel root.

    Class names are a first line of defense, but plugin Choose panels can use
    the same private chooser classes.  Matching the object returned by
    ``find_widget`` closes that ambiguity without scanning or tagging plugin
    panel trees.
    """
    panel_name = str(panel)
    # Test/mocked hosts and a few early IDA startup phases do not expose the
    # find_widget API yet.  In that narrow case the private class/ancestor
    # checks remain the best available boundary; once the API exists, require
    # canonical C++ identity strictly.
    try:
        lookup = getattr(ida_kernwin, "find_widget")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return True
    if lookup is None:
        return True
    canonical = _qt_widget(f"{panel_name} window", panel_name)
    if canonical is None:
        return False
    current = widget
    for _ in range(12):
        if current is None:
            return False
        try:
            if same_qobject(current, canonical):
                return True
            current = current.parentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
    return False


def _is_builtin_strings_table(widget):
    classes = set(_column_meta_names(widget))
    if not classes.intersection({"tchooser_table_widget_t", "chooser_table_widget_t"}):
        return False
    if _column_object_name(widget) != "strings":
        return False
    # The TChooser + object-name boundary excludes third-party Choose tables,
    # even when a plugin happens to use a Strings-like window title.
    return _column_ancestor_has(
        widget,
        class_names=("TChooser", "chooser_widget_t"),
        labels=("strings",),
    ) and _column_under_builtin_lookup(widget, "Strings")


def _is_builtin_tree(widget, panel):
    panel_name = str(panel).casefold()
    classes = set(_column_meta_names(widget))
    if f"{panel_name}_dirtree_widget_t" not in classes:
        return False
    # IDA 9.3 has two legitimate parent layouts for these views.  In a
    # restored desktop the private ``standalone_dirtree_widget_host_t``
    # wrapper is present, while a freshly-created dock can expose the
    # ``*_dirtree_widget_t`` directly as the widget returned by
    # ``find_widget``.  Requiring the host class alone therefore misses the
    # latter (which was the reason Names/Functions kept their native widths).
    # The panel-specific private class is already a strong boundary; combine
    # it with canonical IDA identity when available, and retain the labelled
    # host fallback for early startup/mocked bindings that expose no lookup.
    try:
        # Keep the original display-case title for find_widget(); IDA's
        # lookup is case-sensitive on some builds ("Names" != "names").
        canonical = _column_under_builtin_lookup(widget, panel)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        canonical = False
    if canonical:
        return True
    # Once IDA exposes find_widget(), a failed identity check is a hard
    # boundary: do not fall back to class/title heuristics that could match a
    # third-party tree using a similar private wrapper.  The labelled fallback
    # below is reserved for mocked/early-startup bindings with no lookup API.
    try:
        lookup_available = callable(getattr(ida_kernwin, "find_widget"))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        lookup_available = False
    if lookup_available:
        return False
    return _column_ancestor_has(
        widget,
        class_names=(
            "standalone_dirtree_widget_host_t",
            "standalone_dirtree_widget_t",
        ),
        labels=(panel_name,),
    )


def _column_header(widget, table=False):
    try:
        header = widget.horizontalHeader() if table else widget.header()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    if header is None or not _column_inherits(header, "QHeaderView"):
        return None
    return header


def _header_mode(header, name):
    """Resolve QHeaderView.ResizeMode across PySide6/PyQt5 wrappers."""
    holders = (
        getattr(header, "ResizeMode", None),
        getattr(type(header), "ResizeMode", None),
        header,
        type(header),
    )
    for holder in holders:
        if holder is None:
            continue
        try:
            value = getattr(holder, name)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
        if value is not None:
            return value
    # Qt's enum values are stable for these modes; this fallback is only used
    # by older PyQt wrappers that expose no enum object on QHeaderView.
    return {"Interactive": 0, "Stretch": 1, "Fixed": 2}.get(name)


def _header_section_count(header):
    try:
        return max(0, int(header.count()))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 0


def _header_label(header, index):
    try:
        model = header.model()
        if model is None:
            return ""
        value = model.headerData(index, horizontal_orientation())
        return str(value or "").strip().casefold()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return ""


def _header_font_width(header, text, padding=28):
    try:
        metrics = header.fontMetrics()
        method = getattr(metrics, "horizontalAdvance", None)
        if method is None:
            method = getattr(metrics, "width")
        return int(method(str(text))) + int(padding)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 0


def _clamp(value, minimum, maximum):
    return max(int(minimum), min(int(maximum), int(value)))


def _set_header_mode(header, index, name):
    mode = _header_mode(header, name)
    if mode is None:
        return False
    try:
        header.setSectionResizeMode(int(index), mode)
        return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _resize_header_section(header, index, width):
    try:
        header.resizeSection(int(index), max(1, int(width)))
        return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _header_section_hidden(header, index):
    """Return a section's current visibility without changing user state."""
    try:
        return bool(header.isSectionHidden(int(index)))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _scrollbar_always_off(tree):
    """Hide a built-in tree's horizontal track after columns are fitted."""
    try:
        current = tree.horizontalScrollBarPolicy()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    # PySide6 exposes the enum both as ``Qt.ScrollBarAlwaysOff`` and as
    # ``Qt.ScrollBarPolicy.ScrollBarAlwaysOff`` depending on the build.  The
    # old implementation only inspected the current policy type; on IDA's
    # PySide6 that type has no class attributes, so the call silently fell
    # back to ``1`` (AlwaysOn) and left the track visible.
    try:
        from . import qt_compat as _qt_compat
        qt = getattr(_qt_compat, "Qt", None)
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        qt = None
    enum_holder = getattr(qt, "ScrollBarPolicy", qt)
    holders = (
        getattr(qt, "ScrollBarAlwaysOff", None),
        getattr(enum_holder, "ScrollBarAlwaysOff", None),
        getattr(type(current), "ScrollBarAlwaysOff", None),
        getattr(current, "ScrollBarAlwaysOff", None),
        getattr(tree, "ScrollBarAlwaysOff", None),
    )
    policy = next((value for value in holders if value is not None), None)
    if policy is None:
        return False
    try:
        tree.setHorizontalScrollBarPolicy(policy)
        # A policy change normally hides the native bar on the next layout
        # pass.  Hide the live wrapper as well so a restored desktop cannot
        # flash a one-frame track while Qt recalculates the viewport.
        bar = tree.horizontalScrollBar()
        if bar is not None:
            bar.hide()
        return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _header_marked(header):
    try:
        return str(header.property(_COLUMN_MARK_PROPERTY) or "") == _COLUMN_MARK
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _mark_header(header):
    try:
        header.setProperty(_COLUMN_MARK_PROPERTY, _COLUMN_MARK)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def _apply_strings_columns(table, header):
    if _header_marked(header):
        return None
    count = _header_section_count(header)
    if count < 4:
        return None
    # Keep the address legible at common 96/120 DPI while leaving the String
    # column as the visual breathing room.  The lower bounds avoid reintroducing
    # an unwanted horizontal scrollbar in a normal 400px-wide dock.
    address = _header_font_width(header, "LOAD:0000000000000000", 34)
    length = _header_font_width(header, "00000000", 24)
    kind = _header_font_width(header, "Type", 24)
    address = _clamp(address or 182, 166, 214)
    length = _clamp(length or 88, 78, 104)
    kind = _clamp(kind or 52, 48, 66)
    # Very narrow restored desktops should still fit the three metadata
    # columns; the final String section receives the remaining width.
    try:
        available = int(header.width())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        available = 0
    if 0 < available < address + length + kind + 120:
        scale = max(0.72, (available - 108.0) / float(address + length + kind))
        address = max(142, int(address * scale))
        length = max(72, int(length * scale))
        kind = max(46, int(kind * scale))

    try:
        header.setStretchLastSection(False)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    changed = False
    for index, width in ((0, address), (1, length), (2, kind)):
        changed = _set_header_mode(header, index, "Interactive") or changed
        changed = _resize_header_section(header, index, width) or changed
    # Stretching only the final String column makes the built-in table fill its
    # card instead of reserving a second horizontal scroll track.
    changed = _set_header_mode(header, 3, "Stretch") or changed
    if changed:
        _mark_header(header)
        try:
            header.viewport().update()
            table.viewport().update()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        return {
            "Address": int(address),
            "Length": int(length),
            "Type": int(kind),
            "String": "stretch",
        }
    return None


def _apply_tree_columns(tree, header, panel):
    if _header_marked(header):
        return None
    count = _header_section_count(header)
    if count < 1:
        # Functions may expose an intentionally empty header while the model
        # is still being constructed.  Leave that transient state alone.
        return None
    if count == 1:
        # A one-column Functions tree otherwise grows to the longest symbol
        # and shows a horizontal scrollbar.  Stretching the sole built-in
        # section lets Qt elide long names inside the card instead.
        changed = _set_header_mode(header, 0, "Stretch")
        if not changed:
            return None
        _mark_header(header)
        _scrollbar_always_off(tree)
        try:
            header.viewport().update()
            tree.viewport().update()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        return {"Name": 0, "Address": None, "NameMode": "stretch", "Panel": str(panel)}
    address_index = None
    name_index = None
    segment_index = None
    public_index = None
    for index in range(count):
        label = _header_label(header, index)
        if address_index is None and any(
            token in label for token in ("address", "addr", "ea")
        ):
            address_index = index
        if segment_index is None and any(
            token in label for token in ("segment", "section", "module", "library")
        ):
            segment_index = index
        if name_index is None and any(
            token in label for token in ("name", "function", "symbol")
        ):
            name_index = index
        if public_index is None and any(
            token in label for token in ("public", "visibility", "scope")
        ):
            public_index = index
    if address_index is None:
        address_index = count - 1
    if name_index is None:
        name_index = 0 if address_index != 0 else 1
    if name_index == address_index:
        return None
    panel_name = str(panel).casefold()
    try:
        header.setStretchLastSection(False)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    # The built-in Names tree is Name | Address | Public.  The older generic
    # path stretched Name and fixed Address but left Public at its restored
    # interactive width; on the common three-panel desktop that empty column
    # consumed roughly a third of the card.  Keep both metadata columns
    # compact and deterministic so Name receives the remaining space.
    if panel_name == "names" and count >= 3:
        if public_index is None:
            remaining = [
                index
                for index in range(count)
                if index not in (name_index, address_index)
            ]
            # The exact three-column built-in layout is stable, but retaining
            # the label-first lookup above avoids guessing on future layouts
            # that add more metadata sections.
            if len(remaining) == 1:
                public_index = remaining[0]
        if public_index is not None and public_index not in (
            name_index,
            address_index,
        ):
            address = _header_font_width(header, "0000000000000000", 30)
            address = _clamp(address or 126, 112, 156)
            public = _header_font_width(header, "Public", 28)
            public = _clamp(public or 66, 64, 80)
            name_hidden = _header_section_hidden(header, name_index)
            address_hidden = _header_section_hidden(header, address_index)
            public_hidden = _header_section_hidden(header, public_index)
            changed = False
            # A hidden Names section represents user state.  Do not resize,
            # re-mode, or reveal it; visible sections receive the new layout.
            if not address_hidden:
                changed = _set_header_mode(header, address_index, "Fixed")
                changed = (
                    _resize_header_section(header, address_index, address)
                    or changed
                )
            if not public_hidden:
                changed = (
                    _set_header_mode(header, public_index, "Fixed") or changed
                )
                changed = (
                    _resize_header_section(header, public_index, public) or changed
                )
            if not name_hidden:
                changed = (
                    _set_header_mode(header, name_index, "Stretch") or changed
                )
            all_hidden = name_hidden and address_hidden and public_hidden
            if not changed and not all_hidden:
                return None
            # An all-hidden header is valid user state.  Mark it as migrated
            # without touching any section so later lifecycle notifications
            # do not retry the same no-op indefinitely.
            _mark_header(header)
            if changed:
                _scrollbar_always_off(tree)
                try:
                    header.viewport().update()
                    tree.viewport().update()
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
            return {
                "Name": int(name_index),
                "NameHidden": bool(name_hidden),
                "Address": int(address_index),
                "AddressWidth": int(address),
                "AddressHidden": bool(address_hidden),
                "Public": int(public_index),
                "PublicWidth": int(public),
                "PublicHidden": bool(public_hidden),
                "NameMode": "hidden" if name_hidden else "stretch",
                "Panel": str(panel),
            }

    # IDA's Functions tree is three columns in 9.3 even though its header is
    # visually collapsed: Name | segment (e.g. `.text`) | start address.
    # Keep the short middle column narrow and reserve enough room for the full
    # 64-bit address at the right edge.
    if panel_name == "functions" and count >= 3:
        if address_index is None or address_index == name_index:
            address_index = count - 1
        if segment_index is None or segment_index in (name_index, address_index):
            segment_index = 1 if count > 2 else None
        address = _header_font_width(header, "0000000000000000", 30)
        address = _clamp(address or 138, 128, 156)
        segment = _header_font_width(header, ".text", 24)
        segment = _clamp(segment or 64, 56, 80)
        changed = _set_header_mode(header, address_index, "Fixed")
        changed = _resize_header_section(header, address_index, address) or changed
        # IDA 9.3 keeps the Start/Address section collapsed in a fresh
        # Functions dirtree even though the model exposes it.  Reveal only
        # this built-in metadata section on the first pass; the header mark
        # below makes later lifecycle notifications and user changes in the
        # same session idempotent.  Names and plugin trees are left untouched.
        try:
            if header.isSectionHidden(int(address_index)):
                header.setSectionHidden(int(address_index), False)
                changed = True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        if segment_index is not None and segment_index != address_index:
            changed = _set_header_mode(header, segment_index, "Fixed") or changed
            changed = _resize_header_section(header, segment_index, segment) or changed
        changed = _set_header_mode(header, name_index, "Stretch") or changed
    else:
        address_label = _header_label(header, address_index)
        address_tokens = ("address", "addr", "ea")
        if panel_name == "functions" and not any(
            token in address_label for token in address_tokens
        ):
            # Two-column fallback for older IDA builds using Name | segment.
            address = _header_font_width(header, ".plt", 24)
            address = _clamp(address or 58, 48, 88)
        else:
            address = _header_font_width(header, "0000000000000000", 30)
            address = _clamp(address or 126, 112, 156)
        changed = _set_header_mode(header, address_index, "Fixed")
        changed = _resize_header_section(header, address_index, address) or changed
        changed = _set_header_mode(header, name_index, "Stretch") or changed
    if not changed:
        return None
    _mark_header(header)
    _scrollbar_always_off(tree)
    try:
        header.viewport().update()
        tree.viewport().update()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return {
        "Name": int(name_index),
        "Address": int(address_index),
        "AddressWidth": int(address),
        "NameMode": "stretch",
        "Panel": str(panel),
    }


def _column_targets(root=None):
    app = QApplication.instance()
    if app is None:
        return []
    if root is None:
        try:
            widgets = list(app.allWidgets())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            widgets = []
    else:
        widgets = list(_column_walk(root))
    targets = []
    seen = set()
    for widget in widgets:
        panel = None
        table = False
        if _is_builtin_strings_table(widget):
            panel = "Strings"
            table = True
        elif _is_builtin_tree(widget, "Names"):
            panel = "Names"
        elif _is_builtin_tree(widget, "Functions"):
            panel = "Functions"
        if panel is None:
            continue
        header = _column_header(widget, table=table)
        if header is None:
            continue
        try:
            key = qobject_key(header)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            key = id(header)
        if key in seen:
            continue
        seen.add(key)
        targets.append((panel, widget, header, table))
    return targets


def apply_builtin_column_layout(root=None):
    """Apply one-time widths to built-in Strings/Names/Functions only.

    ``root`` is used by ``widget_visible`` to keep the scan local.  A native
    dynamic property on each header makes the operation idempotent and avoids
    overwriting a user's later manual resize.  No timer, global event filter,
    resize hook, or paint callback is involved.
    """
    _column_diagnostics["attempt_count"] += 1
    applied = 0
    unavailable = 0
    for panel, widget, header, table in _column_targets(root):
        if panel == "Strings":
            result = _apply_strings_columns(widget, header)
        else:
            result = _apply_tree_columns(widget, header, panel)
        if result is None:
            if not _header_marked(header):
                unavailable += 1
            continue
        applied += 1
        _column_diagnostics[panel.casefold()] = result
    if applied:
        _column_diagnostics["apply_count"] += applied
        _column_diagnostics["last_result"] = "applied"
    elif unavailable:
        _column_diagnostics["last_result"] = "targets-unavailable"
    else:
        _column_diagnostics["last_result"] = "already-applied"
    return bool(applied)


def column_layout_runtime_diagnostics():
    return {
        "attempt_count": int(_column_diagnostics["attempt_count"]),
        "apply_count": int(_column_diagnostics["apply_count"]),
        "strings": dict(_column_diagnostics["strings"]),
        "names": dict(_column_diagnostics["names"]),
        "functions": dict(_column_diagnostics["functions"]),
        "last_result": str(_column_diagnostics["last_result"]),
    }


def layout_runtime_diagnostics():
    return {
        "attempt_count": int(_diagnostics["attempt_count"]),
        "apply_count": int(_diagnostics["apply_count"]),
        "horizontal_sizes": list(_diagnostics["horizontal_sizes"]),
        "vertical_sizes": list(_diagnostics["vertical_sizes"]),
        "top_horizontal_sizes": list(_diagnostics["top_horizontal_sizes"]),
        "target_widths": list(_diagnostics["target_widths"]),
        "mode": str(_diagnostics["mode"]),
        "last_result": str(_diagnostics["last_result"]),
    }


__all__ = [
    "BASE_LAYOUT_VERSION",
    "COLUMN_LAYOUT_VERSION",
    "TARGET_LAYOUT_VERSION",
    "apply_balanced_panel_layout",
    "apply_balanced_three_panel_layout",
    "apply_builtin_column_layout",
    "column_layout_runtime_diagnostics",
    "layout_runtime_diagnostics",
]
