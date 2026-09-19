"""Static regression checks for IDA's Text search dialog styling."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QSS_PATH = ROOT / "src" / "ida_modern_ui" / "themes" / "modern_dark.qss"
SCOPE = 'ui_form_dialog_t[windowTitle="Text search (slow!)"] > ida_form_widget_t'


def main() -> None:
    qss = QSS_PATH.read_text(encoding="utf-8")
    required = (
        f"{SCOPE} > buddy_label_t",
        f"{SCOPE} > QComboBox",
        f"{SCOPE} > QComboBox:hover",
        f"{SCOPE} > QComboBox:focus",
        f"{SCOPE} > QComboBox:open",
        f"{SCOPE} > QComboBox:disabled",
        f"{SCOPE} > QComboBox::drop-down:hover",
        f"{SCOPE} > QComboBox::drop-down:pressed",
        f"{SCOPE} > QComboBox QAbstractItemView",
        f"{SCOPE} > QGroupBox",
        f"{SCOPE} > QDialogButtonBox > QPushButton:default",
        f"{SCOPE} > QDialogButtonBox > QPushButton:default:hover:pressed",
        f"{SCOPE} > QDialogButtonBox > QPushButton:default:disabled",
        f"{SCOPE} > QDialogButtonBox > QPushButton:disabled",
    )
    missing = [selector for selector in required if selector not in qss]
    if missing:
        raise SystemExit("TEXT_SEARCH_QSS_MISSING " + ", ".join(missing))

    combo_match = re.search(
        re.escape(f"{SCOPE} > QComboBox") + r"\s*\{(?P<body>.*?)\}",
        qss,
        re.DOTALL,
    )
    if combo_match is None:
        raise SystemExit("TEXT_SEARCH_QSS_MISSING combo block")
    body = combo_match.group("body")
    for declaration in ("max-width: 239px", "min-height: 28px", "padding: 0 28px 0 9px"):
        if declaration not in body:
            raise SystemExit("TEXT_SEARCH_QSS_BAD_GEOMETRY " + declaration)
    if "max-height" in body:
        raise SystemExit("TEXT_SEARCH_QSS_BAD_GEOMETRY fixed max-height")

    drop_down_match = re.search(
        re.escape(f"{SCOPE} > QComboBox::drop-down") + r"\s*\{(?P<body>.*?)\}",
        qss,
        re.DOTALL,
    )
    if drop_down_match is None or any(
        declaration not in drop_down_match.group("body")
        for declaration in (
            "border-top-right-radius: @SMALL_RADIUS@",
            "border-bottom-right-radius: @SMALL_RADIUS@",
        )
    ):
        raise SystemExit("TEXT_SEARCH_QSS_BAD_GEOMETRY drop-down corner radius")

    print(
        "TEXT_SEARCH_QSS_OK "
        "scope=Text_search combo=single_layer/239x28 buttons=hierarchical states=complete"
    )


if __name__ == "__main__":
    main()
