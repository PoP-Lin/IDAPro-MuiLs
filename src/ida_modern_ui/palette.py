# -*- coding: utf-8 -*-
"""Theme palette transforms.

``modern_dark`` is the authored palette.  ``modern_oled`` is derived from it at
apply time: every dark surface colour is pushed toward true black (#000000) so
OLED panels switch those pixels off, while mid-tones, text and accents keep
their hue and relative contrast.  All Python runtimes route their colour
literals through :func:`c` so the derived theme stays consistent with the QSS.
"""

from __future__ import annotations

import colorsys
import re

_active_theme = "modern_dark"
_cache: dict = {}

# (input lightness, output lightness) breakpoints for the OLED curve.
_OLED_CURVE = ((0.0, 0.0), (0.115, 0.0), (0.13, 0.045), (0.32, 0.235), (0.45, 0.45))

_HEX_RE = re.compile(r"#([0-9a-fA-F]{6})\b")
_RGBA_RE = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(,\s*[0-9.]+\s*)?\)")


def set_theme(name: str) -> None:
    global _active_theme
    _active_theme = "modern_oled" if name == "modern_oled" else "modern_dark"
    _cache.clear()


def active_theme() -> str:
    return _active_theme


def _oled_lightness(value: float) -> float:
    points = _OLED_CURVE
    if value >= points[-1][0]:
        return value
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= value <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return value


def _transform_rgb(r: int, g: int, b: int) -> tuple:
    if _active_theme != "modern_oled":
        return r, g, b
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    new_l = _oled_lightness(l)
    if new_l == l:
        return r, g, b
    nr, ng, nb = colorsys.hls_to_rgb(h, new_l, s)
    return round(nr * 255), round(ng * 255), round(nb * 255)


def c(value: str) -> str:
    """Return ``value`` (a ``#RRGGBB`` string) mapped into the active theme."""
    if _active_theme == "modern_dark" or not isinstance(value, str):
        return value
    key = value.upper()
    cached = _cache.get(key)
    if cached is not None:
        return cached
    match = _HEX_RE.fullmatch(key)
    if match is None:
        return value
    r, g, b = (int(key[i : i + 2], 16) for i in (1, 3, 5))
    r, g, b = _transform_rgb(r, g, b)
    result = f"#{r:02X}{g:02X}{b:02X}"
    _cache[key] = result
    return result


def transform_text(text: str) -> str:
    """Map every hex / rgb() colour literal in a stylesheet into the theme."""
    if _active_theme == "modern_dark":
        return text

    def hex_sub(match):
        return c("#" + match.group(1))

    def rgba_sub(match):
        r, g, b = (int(match.group(i)) for i in (1, 2, 3))
        r, g, b = _transform_rgb(r, g, b)
        tail = match.group(4) or ""
        return f"rgb{'a' if tail else ''}({r}, {g}, {b}{tail})"

    return _RGBA_RE.sub(rgba_sub, _HEX_RE.sub(hex_sub, text))


__all__ = ["active_theme", "c", "set_theme", "transform_text"]
