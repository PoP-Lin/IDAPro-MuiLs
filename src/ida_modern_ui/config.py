# -*- coding: utf-8 -*-
"""Persistent configuration for IDAPro-MuiLs."""

from __future__ import annotations

import json
import re
import sys
from copy import deepcopy
from pathlib import Path

import ida_diskio

PACKAGE_DIR = Path(__file__).resolve().parent
PACKAGE_CONFIG_PATH = PACKAGE_DIR / "config.json"
CONFIG_DIR = Path(ida_diskio.get_user_idadir()) / "modern_ui"
CONFIG_PATH = CONFIG_DIR / "config.json"

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

THEMES = ("modern_dark", "modern_oled")

DEFAULT_CONFIG = {
    "enabled": True,
    "theme": "modern_dark",
    "accent": "#7AA2F7",
    "font_family": "Helvetica Neue" if IS_MACOS else "Segoe UI",
    "font_size": 11 if IS_MACOS else 10,
    "code_font_family": "SF Mono" if IS_MACOS else "Cascadia Mono",
    "corner_radius": 10,
    "density": "comfortable",
    "smooth_resize": True,
    "style_plugin_panels": True,
    # The balanced splitter/column layout rewrites the saved IDA desktop.  It
    # is opt-in outside Windows so enabling the theme changes pixels only.
    "apply_panel_layout": IS_WINDOWS,
    "panel_layout_version": 0,
}


def load_config() -> dict:
    config = deepcopy(DEFAULT_CONFIG)
    source_path = CONFIG_PATH if CONFIG_PATH.exists() else PACKAGE_CONFIG_PATH
    try:
        loaded = json.loads(source_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            config.update(loaded)
    except (OSError, ValueError, TypeError):
        pass
    return normalize_config(config)


def normalize_config(config: dict) -> dict:
    normalized = deepcopy(DEFAULT_CONFIG)
    if isinstance(config, dict):
        for key in DEFAULT_CONFIG:
            if key in config:
                normalized[key] = config[key]
    normalized["enabled"] = _as_bool(
        normalized["enabled"], DEFAULT_CONFIG["enabled"]
    )
    normalized["smooth_resize"] = _as_bool(
        normalized["smooth_resize"], DEFAULT_CONFIG["smooth_resize"]
    )
    normalized["style_plugin_panels"] = _as_bool(
        normalized["style_plugin_panels"], DEFAULT_CONFIG["style_plugin_panels"]
    )
    normalized["apply_panel_layout"] = _as_bool(
        normalized["apply_panel_layout"], DEFAULT_CONFIG["apply_panel_layout"]
    )
    normalized["font_size"] = _bounded_int(
        normalized["font_size"], 8, 16, DEFAULT_CONFIG["font_size"]
    )
    normalized["corner_radius"] = _bounded_int(
        normalized["corner_radius"], 0, 14, DEFAULT_CONFIG["corner_radius"]
    )
    normalized["panel_layout_version"] = _bounded_int(
        normalized["panel_layout_version"],
        0,
        1000,
        DEFAULT_CONFIG["panel_layout_version"],
    )
    normalized["density"] = (
        normalized["density"] if normalized["density"] in {"compact", "comfortable"} else "comfortable"
    )
    normalized["theme"] = (
        normalized["theme"] if normalized["theme"] in THEMES else "modern_dark"
    )
    accent = str(normalized["accent"]).upper()
    normalized["accent"] = accent if re.fullmatch(r"#[0-9A-F]{6}", accent) else "#7AA2F7"
    for key in ("font_family", "code_font_family"):
        raw_value = normalized[key]
        value = "" if raw_value is None else str(raw_value)
        value = re.sub(r"[^\w .,+-]", "", value, flags=re.UNICODE).strip()
        normalized[key] = value or DEFAULT_CONFIG[key]
    return normalized


def _as_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        candidate = value.strip().casefold()
        if candidate in {"1", "true", "yes", "on"}:
            return True
        if candidate in {"0", "false", "no", "off"}:
            return False
    return bool(default)


def _bounded_int(value, minimum, maximum, default):
    try:
        candidate = int(value)
    except (TypeError, ValueError, OverflowError):
        candidate = int(default)
    return max(int(minimum), min(int(maximum), candidate))


def save_config(config: dict) -> dict:
    normalized = normalize_config(config)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = CONFIG_PATH.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(CONFIG_PATH)
    return normalized
