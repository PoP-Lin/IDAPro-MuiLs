#!/usr/bin/env python3
"""Static regression checks for the built-in quick-filter QSS geometry."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QSS_PATH = ROOT / "src" / "ida_modern_ui" / "themes" / "modern_dark.qss"
QSS = QSS_PATH.read_text(encoding="utf-8")
ERRORS: list[str] = []

CHOOSER_PREFIXES = (
    "TChooser > quick_filter_widget_t",
    "chooser_widget_t > quick_filter_widget_t",
)
DIRTREE_PREFIX = "standalone_dirtree_widget_host_t > quick_filter_widget_t"
ALLOWED_QUICK_FILTER_PREFIXES = (*CHOOSER_PREFIXES, DIRTREE_PREFIX)


def rule_body(selectors: tuple[str, ...], label: str) -> str:
    pattern = r"\s*,\s*".join(re.escape(selector) for selector in selectors)
    match = re.search(pattern + r"\s*\{([^{}]*)\}", QSS, flags=re.MULTILINE)
    if match is None:
        ERRORS.append(f"missing selector group: {label}")
        return ""
    return match.group(1)


def declaration(body: str, name: str) -> str | None:
    match = re.search(
        rf"(?:^|;)\s*{re.escape(name)}\s*:\s*([^;]+)\s*;",
        body,
        flags=re.MULTILINE,
    )
    return match.group(1).strip() if match else None


chooser_inputs = (
    f"{CHOOSER_PREFIXES[0]} > quick_filter_input_t",
    f"{CHOOSER_PREFIXES[1]} > quick_filter_input_t",
    f"{CHOOSER_PREFIXES[0]} > quick_filter_input_t:focus",
    f"{CHOOSER_PREFIXES[1]} > quick_filter_input_t:focus",
)
dirtree_inputs = (
    f"{DIRTREE_PREFIX} > quick_filter_input_t",
    f"{DIRTREE_PREFIX} > quick_filter_input_t:focus",
)
chooser_buttons = tuple(f"{prefix} > QPushButton" for prefix in CHOOSER_PREFIXES)
dirtree_buttons = (f"{DIRTREE_PREFIX} > QPushButton",)

for label, selectors in (
    ("chooser input normal/focus", chooser_inputs),
    ("dirtree input normal/focus", dirtree_inputs),
):
    body = rule_body(selectors, label)
    padding = declaration(body, "padding")
    # The source stylesheet keeps the vertical inset density-aware.  The
    # rendered stylesheet substitutes @CONTROL_V@ (3px/5px), while older
    # releases used a literal zero.  Normalize the token for this geometry
    # check instead of rejecting a valid compact/comfortable build.
    normalized_padding = (padding or "").replace("@CONTROL_V@", "0")
    if normalized_padding != "0 8px 0 0":
        ERRORS.append(
            f"{label}: expected asymmetric padding '0 8px 0 0', got {padding!r}"
        )
    for property_name, expected in (
        ("background", "transparent"),
        ("border", "0"),
        ("margin", "0"),
    ):
        actual = declaration(body, property_name)
        if actual != expected:
            ERRORS.append(
                f"{label}: expected {property_name}={expected!r}, got {actual!r}"
            )

for label, selectors in (
    ("chooser clear button", chooser_buttons),
    ("dirtree clear button", dirtree_buttons),
):
    body = rule_body(selectors, label)
    for property_name, expected in (
        ("background", "transparent"),
        ("border", "0"),
        ("margin", "5px 1px"),
        ("padding", "0"),
    ):
        actual = declaration(body, property_name)
        if actual != expected:
            ERRORS.append(
                f"{label}: expected {property_name}={expected!r}, got {actual!r}"
            )
    if declaration(body, "border-right") is not None:
        ERRORS.append(f"{label}: hard input divider must remain removed")
    for persistent_property in ("qproperty-icon", "qproperty-iconSize"):
        if declaration(body, persistent_property) is not None:
            ERRORS.append(
                f"{label}: {persistent_property} would survive stylesheet restore"
            )
    if re.search(r"(?:^|;)\s*(?:min-|max-)?width\s*:", body, flags=re.MULTILINE):
        ERRORS.append(f"{label}: fixed width would break native DPI-aware geometry")

for label, selectors in (
    ("chooser surface", CHOOSER_PREFIXES),
    ("dirtree surface", (DIRTREE_PREFIX,)),
):
    body = rule_body(selectors, label)
    if declaration(body, "margin") != "0 10px 3px 10px":
        ERRORS.append(f"{label}: horizontal 10px alignment inset regressed")

focus_surfaces = (
    f'{CHOOSER_PREFIXES[0]}[modernUiQuickFilterFocusWithin="true"]',
    f'{CHOOSER_PREFIXES[1]}[modernUiQuickFilterFocusWithin="true"]',
)
for label, selectors in (
    ("chooser focused surface", focus_surfaces),
    (
        "dirtree focused surface",
        (f'{DIRTREE_PREFIX}[modernUiQuickFilterFocusWithin="true"]',),
    ),
):
    body = rule_body(selectors, label)
    for property_name, expected in (
        ("background", "#101722"),
        ("border-color", "#52677F"),
    ):
        actual = declaration(body, property_name)
        if actual != expected:
            ERRORS.append(
                f"{label}: expected {property_name}={expected!r}, got {actual!r}"
            )

# Every quick-filter selector must retain an explicit built-in host prefix.
# This prevents the compact geometry from leaking into plugin-owned line edits.
qss_without_comments = re.sub(r"/\*.*?\*/", "", QSS, flags=re.DOTALL)
for selector_group, _body in re.findall(r"([^{}]+)\{([^{}]*)\}", qss_without_comments):
    for selector in selector_group.split(","):
        selector = " ".join(selector.split())
        if "quick_filter_" not in selector:
            continue
        if not selector.startswith(ALLOWED_QUICK_FILTER_PREFIXES):
            ERRORS.append(f"unscoped quick-filter selector: {selector}")

if ERRORS:
    raise SystemExit("QUICK_FILTER_QSS_FAILED\n- " + "\n- ".join(ERRORS))

print(
    "QUICK_FILTER_QSS_OK "
    "scopes=all_host_choosers,standalone_dirtree "
    "input_padding=0_8px_0_0 clear_icon=runtime_reversible divider=none "
    "focus_within=restrained fixed_width=none"
)
