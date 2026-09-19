#!/usr/bin/env python3
"""Static regression checks for IDA's G / Jump-to-address form styling."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QSS_PATH = ROOT / "src" / "ida_modern_ui" / "themes" / "modern_dark.qss"
QSS = QSS_PATH.read_text(encoding="utf-8")
ERRORS: list[str] = []
JUMP = 'ui_form_dialog_t[windowTitle="Jump to address"] > ida_form_widget_t'


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


inner = rule_body(
    (
        "ui_form_dialog_t QComboBox > input_field_t",
        "ui_form_dialog_t QComboBox > input_field_t:focus",
    ),
    "IDA editable-combo inner editor reset",
)
for name, expected in (
    ("background", "transparent"),
    ("border", "0"),
    ("border-radius", "0"),
    ("margin", "0"),
    ("min-height", "0"),
    ("padding", "0"),
    ("selection-background-color", "#31405A"),
    ("selection-color", "#F0F4FA"),
):
    actual = declaration(inner, name)
    if actual != expected:
        ERRORS.append(f"inner editor: expected {name}={expected!r}, got {actual!r}")

combo = rule_body((f"{JUMP} > QComboBox",), "Jump address combo")
for name, expected in (
    ("background", "#111820"),
    ("border", "1px solid #3B4859"),
    ("border-radius", "@SMALL_RADIUS@"),
    ("min-width", "213px"),
    ("max-width", "213px"),
    ("min-height", "28px"),
    ("margin-left", "2px"),
    ("padding", "0 28px 0 9px"),
):
    actual = declaration(combo, name)
    if actual != expected:
        ERRORS.append(f"Jump combo: expected {name}={expected!r}, got {actual!r}")

focus = rule_body((f"{JUMP} > QComboBox:focus",), "Jump address focus")
if declaration(focus, "border-color") != "#52677F":
    ERRORS.append("Jump combo: focus border must remain the restrained #52677F")

drop_down = rule_body((f"{JUMP} > QComboBox::drop-down",), "Jump address drop-down")
for name in ("border-top-right-radius", "border-bottom-right-radius"):
    if declaration(drop_down, name) != "@SMALL_RADIUS@":
        ERRORS.append(f"Jump combo: {name} must follow the rounded outer field")

buttons = rule_body(
    (f"{JUMP} > QDialogButtonBox > QPushButton",),
    "Jump address buttons",
)
for name, expected in (
    ("border-radius", "@CONTROL_RADIUS@"),
    ("min-width", "40px"),
    ("min-height", "28px"),
):
    actual = declaration(buttons, name)
    if actual != expected:
        ERRORS.append(f"Jump buttons: expected {name}={expected!r}, got {actual!r}")

for label, body in (("Jump combo", combo), ("Jump buttons", buttons)):
    if declaration(body, "max-height") is not None:
        ERRORS.append(f"{label}: fixed max-height would clip supported large fonts")

default_button = rule_body(
    (f"{JUMP} > QDialogButtonBox > QPushButton:default",),
    "Jump address default button",
)
if declaration(default_button, "background") != "#2C3B4E":
    ERRORS.append("Jump buttons: default action hierarchy is missing")

pressed_default = rule_body(
    (
        f"{JUMP} > QDialogButtonBox > QPushButton:default:hover:pressed",
        f"{JUMP} > QDialogButtonBox > QPushButton:default:focus:pressed",
    ),
    "Jump address pressed default button",
)
if declaration(pressed_default, "background") != "#1D2734":
    ERRORS.append("Jump buttons: pressed default action must override hover/focus")

disabled_default = rule_body(
    (f"{JUMP} > QDialogButtonBox > QPushButton:default:disabled",),
    "Jump address disabled default button",
)
if declaration(disabled_default, "background") != "#1B2027":
    ERRORS.append("Jump buttons: disabled default action must stay visibly disabled")

# Geometry-changing IDA form rules must retain an exact built-in title
# boundary.  This keeps Jump isolated while allowing separately verified
# dialogs, such as Text search, to use their own compact geometry.
qss_without_comments = re.sub(r"/\*.*?\*/", "", QSS, flags=re.DOTALL)
for selector_group, body in re.findall(r"([^{}]+)\{([^{}]*)\}", qss_without_comments):
    if not re.search(r"(?:min|max)-(?:width|height)\s*:", body):
        continue
    for selector in selector_group.split(","):
        selector = " ".join(selector.split())
        if (
            "ida_form_widget_t" in selector
            and not selector.startswith('ui_form_dialog_t[windowTitle="')
        ):
            ERRORS.append(f"unscoped IDA form geometry selector: {selector}")

if ERRORS:
    raise SystemExit("JUMP_DIALOG_QSS_FAILED\n- " + "\n- ".join(ERRORS))

print(
    "JUMP_DIALOG_QSS_OK scope=Jump_to_address "
    "combo=single_layer/213x28 focus=#52677F buttons=hierarchical"
)
