# -*- coding: utf-8 -*-
"""Targeted styling for IDA's custom-painted analysis widgets."""

from __future__ import annotations

from .qt_compat import QApplication, QColor, QWidget


COLORS = {
    "CustomIDAMemo": {
        "line-bg-default": "#111318",
        "line-bg-selected": "#34415B",
        "line-fg-default": "#C8D0DC",
        "line-fg-regular-comment": "#7A8495",
        "line-fg-repeatable-comment": "#8892A3",
        "line-fg-automatic-comment": "#626C7C",
        "line-fg-insn": "#D7DEE8",
        "line-fg-dummy-data-name": "#9FB5D1",
        "line-fg-regular-data-name": "#A9C1DE",
        "line-fg-demangled-name": "#82AAFF",
        "line-fg-punctuation": "#AAB4C3",
        "line-fg-charlit-in-insn": "#C3E88D",
        "line-fg-strlit-in-insn": "#C3E88D",
        "line-fg-numlit-in-insn": "#F78C6C",
        "line-fg-void-opnd": "#FF6B7A",
        "line-fg-code-xref": "#89DDFF",
        "line-fg-data-xref": "#7FDBCA",
        "line-fg-error": "#FF5370",
        "line-fg-line-prefix": "#697386",
        "line-fg-opcode-byte": "#596273",
        "line-fg-extra-line": "#C792EA",
        "line-fg-alt-opnd": "#D4A8FF",
        "line-fg-hidden": "#FFCB6B",
        "line-fg-libfunc": "#89DDFF",
        "line-fg-locvar": "#F78C6C",
        "line-fg-dummy-code-name": "#82AAFF",
        "line-fg-asm-directive": "#C3E88D",
        "line-fg-macro": "#C792EA",
        "line-fg-strlit-in-data": "#C3E88D",
        "line-fg-charlit-in-data": "#C3E88D",
        "line-fg-numlit-in-data": "#F78C6C",
        "line-fg-keyword": "#C792EA",
        "line-fg-register-name": "#89DDFF",
        "line-fg-import-name": "#D4A8FF",
        "line-fg-segment-name": "#FFCB6B",
        "line-fg-code-name": "#82AAFF",
        "line-fg-unknown-name": "#D4A8FF",
        "graph-bg-top": "#141820",
        "graph-bg-bottom": "#0F1218",
        "graph-node-title-normal": "#252B35",
        "graph-node-title-selected": "#34415B",
        "graph-node-title-current": "#2D3A4D",
        "graph-node-shadow": "#0B0D12",
        "graph-edge-normal": "#697386",
        "graph-edge-yes": "#73D18B",
        "graph-edge-no": "#FF6B7A",
        "graph-edge-high": "#82AAFF",
        "graph-edge-selected": "#FFCB6B",
        "graph-node-frame-selected": "#82AAFF",
    },
    "viewer_t": {
        "viewer-bg": "#111318",
        "node-bg-import": "#553C58",
        "node-bg-code": "#253A59",
        "node-bg-data": "#294A3A",
        "node-bg-default": "#303641",
        "node-border": "#758195",
        "node-text": "#E2E8F0",
        "edge-default": "#697386",
        "edge-highlighted": "#82AAFF",
    },
    "navband_t": {
        "lib-function": "#50A9A8",
        "function": "#347FB1",
        "code": "#9D6858",
        "data": "#818895",
        "undefined": "#777651",
        "extern": "#9D619E",
        "lumina-function": "#469958",
        "gap": "#303641",
        "cursor": "#A8C7FA",
        "auto-analysis-cursor": "#D8A657",
    },
}


def _inherits(widget, target_name):
    meta = widget.metaObject()
    while meta is not None:
        if meta.className() == target_name:
            return True
        meta = meta.superClass()
    return False


def _targets(root=None):
    app = QApplication.instance()
    if app is None:
        return []
    if root is None:
        return list(app.allWidgets())
    return [root, *root.findChildren(QWidget)]


def apply_analysis_palette(root=None):
    """Set only documented custom properties; leave plugin widgets untouched."""
    for widget in _targets(root):
        for class_name, properties in COLORS.items():
            if not _inherits(widget, class_name):
                continue
            meta = widget.metaObject()
            for property_name, color in properties.items():
                try:
                    if meta.indexOfProperty(property_name) >= 0:
                        widget.setProperty(property_name, QColor(color))
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    continue
            widget.update()
            break


def repolish_analysis_widgets(root=None):
    """Let the active native stylesheet restore its custom properties."""
    for widget in _targets(root):
        if not any(_inherits(widget, class_name) for class_name in COLORS):
            continue
        try:
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)
            widget.update()
        except (AttributeError, RuntimeError, TypeError):
            continue
