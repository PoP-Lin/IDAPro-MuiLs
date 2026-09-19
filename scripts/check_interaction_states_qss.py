"""Static contract for the theme's common interactive control states."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QSS_PATH = ROOT / "src" / "ida_modern_ui" / "themes" / "modern_dark.qss"


REQUIRED = {
    "menu": (
        "QMenuBar::item:pressed",
        "QMenuBar::item:disabled",
        "QMenu::item:selected",
        "QMenu::item:checked",
        "QMenu::item:checked:disabled",
        "QMenu::item:disabled",
        "QMenu::indicator:checked:disabled",
    ),
    "tool_button": (
        "QToolButton:hover",
        "QToolButton:focus",
        "QToolButton:pressed",
        "QToolButton:checked",
        "QToolButton:open",
        "QToolButton:disabled",
        "QToolButton:checked:focus",
        "QToolButton:checked:pressed",
    ),
    "push_button": (
        "QPushButton:hover",
        "QPushButton:focus",
        "QPushButton:pressed",
        "QPushButton:checked",
        "QPushButton:disabled",
        "QPushButton:checked:focus",
        "QPushButton:checked:pressed",
    ),
    "text_input": (
        "QLineEdit:hover",
        "QLineEdit:focus",
        "QLineEdit:read-only",
        "QLineEdit:read-only:focus",
        "QLineEdit:disabled",
        "placeholder-text-color:",
    ),
    "combo": (
        "QComboBox:hover",
        "QComboBox:focus",
        "QComboBox:open",
        "QComboBox:disabled",
        "QComboBox::drop-down:hover",
        "QComboBox::drop-down:pressed",
        "QComboBox QAbstractItemView::item:selected",
    ),
    "spin": (
        "QSpinBox:focus",
        "QSpinBox:disabled",
        "QSpinBox::up-button:hover",
        "QSpinBox::up-button:pressed",
        "QSpinBox::up-button:disabled",
    ),
    "choice": (
        "QCheckBox::indicator:hover",
        "QCheckBox::indicator:focus",
        "QCheckBox::indicator:pressed",
        "QCheckBox::indicator:checked",
        "QCheckBox::indicator:indeterminate",
        "QCheckBox::indicator:indeterminate:disabled",
        "QCheckBox::indicator:checked:focus",
        "QCheckBox:disabled",
        "QRadioButton::indicator:hover",
        "QRadioButton::indicator:focus",
        "QRadioButton::indicator:pressed",
        "QRadioButton::indicator:checked",
        "QRadioButton::indicator:checked:disabled",
        "QRadioButton:disabled",
    ),
    "item_view": (
        "QTreeView::item:hover",
        "QTreeView::item:selected",
        "QTreeView::item:selected:!active",
        "QTreeView::item:disabled",
        "QHeaderView::section:hover",
        "QHeaderView::section:pressed",
        "QHeaderView::section:disabled",
        "QTreeView::branch:closed:has-children",
        "QTreeView::branch:open:has-children",
        "QHeaderView::up-arrow",
        "QHeaderView::down-arrow",
    ),
    "table_corner": (
        "QTableCornerButton::section {",
        "QTableCornerButton::section:hover",
        "QTableCornerButton::section:pressed",
        "QTableCornerButton::section:disabled",
    ),
    "tab": (
        "QTabBar::tab:pressed",
        "QTabBar::tab:selected:disabled",
        "QTabBar::close-button:pressed",
    ),
    "dialog_default_button": (
        'ui_form_dialog_t[windowTitle="Jump to address"] > ida_form_widget_t > QDialogButtonBox > QPushButton:default:pressed',
        'ui_form_dialog_t[windowTitle="Jump to address"] > ida_form_widget_t > QDialogButtonBox > QPushButton:default:hover:pressed',
        'ui_form_dialog_t[windowTitle="Jump to address"] > ida_form_widget_t > QDialogButtonBox > QPushButton:default:disabled',
        'ui_form_dialog_t[windowTitle="Text search (slow!)"] > ida_form_widget_t > QDialogButtonBox > QPushButton:default:pressed',
        'ui_form_dialog_t[windowTitle="Text search (slow!)"] > ida_form_widget_t > QDialogButtonBox > QPushButton:default:hover:pressed',
        'ui_form_dialog_t[windowTitle="Text search (slow!)"] > ida_form_widget_t > QDialogButtonBox > QPushButton:default:disabled',
    ),
    "slider": (
        "QSlider::groove:horizontal",
        "QSlider::handle:horizontal:hover",
        "QSlider::handle:horizontal:focus",
        "QSlider::handle:horizontal:pressed",
        "QSlider::handle:horizontal:disabled",
        "QSlider::groove:vertical",
        "QSlider::handle:vertical:hover",
        "QSlider::handle:vertical:pressed",
        "QSlider::handle:vertical:disabled",
    ),
    "scrollbar_splitter": (
        "QScrollBar::handle:hover",
        "QScrollBar::handle:pressed",
        "QScrollBar::handle:disabled",
        "log_widget_t QScrollBar::handle:vertical:pressed",
        "log_widget_t QScrollBar::handle:vertical:disabled",
        "tchooser_table_widget_t#Strings QScrollBar::handle:vertical:pressed",
        "tchooser_table_widget_t#Strings QScrollBar::handle:vertical:disabled",
        "standalone_dirtree_widget_t QScrollBar::handle:vertical:pressed",
        "standalone_dirtree_widget_t QScrollBar::handle:vertical:disabled",
        "QSplitter::handle:horizontal:hover",
        "QSplitter::handle:horizontal:pressed",
    ),
    "scoped_search": (
        'QLineEdit[modernUiPluginPanel="adaptive"][modernUiPanelRole="search"]:focus',
        'QLineEdit[modernUiPluginPanel="adaptive"][modernUiPanelRole="search"]:disabled',
        'quick_filter_widget_t[modernUiQuickFilterFocusWithin="true"]',
        "quick_filter_input_t:disabled",
    ),
    "plugin_item_view": (
        'QHeaderView[modernUiPluginPanel="adaptive"][modernUiPanelRole="header"]::section:hover',
        'QHeaderView[modernUiPluginPanel="adaptive"][modernUiPanelRole="header"]::section:pressed',
        'QHeaderView[modernUiPluginPanel="adaptive"][modernUiPanelRole="header"]::section:disabled',
        'QTreeView[modernUiPluginPanel="adaptive"][modernUiPanelRole="tree"]::item:selected:!active',
        'QTableView[modernUiPluginPanel="adaptive"][modernUiPanelRole="table"]::item:selected:!active',
        'QListView[modernUiPluginPanel="adaptive"][modernUiPanelRole="list"]::item:selected:!active',
        "tchooser_table_widget_t#Strings > QHeaderView::section:hover",
        "tchooser_table_widget_t#Strings > QHeaderView::section:pressed",
        "tchooser_table_widget_t#Strings > QHeaderView::section:disabled",
        "tchooser_table_widget_t#Strings::item:selected:!active",
    ),
    "plugin_console": (
        'QLineEdit[modernUiPluginPanel="adaptive"][modernUiPanelRole="search"]:read-only:focus',
        'QPlainTextEdit[modernUiPluginPanel="adaptive"][modernUiPanelRole="console"]:read-only',
        'QPlainTextEdit[modernUiPluginPanel="adaptive"][modernUiPanelRole="console"]:read-only:focus',
        'QPlainTextEdit[modernUiPluginPanel="adaptive"][modernUiPanelRole="console"]:disabled',
    ),
    "dock_subcontrols": (
        "QDockWidget::close-button:hover",
        "QDockWidget::close-button:pressed",
        "QDockWidget::float-button:hover",
        "QDockWidget::float-button:pressed",
    ),
}


def main() -> None:
    qss = QSS_PATH.read_text(encoding="utf-8")
    missing = {
        family: [selector for selector in selectors if selector not in qss]
        for family, selectors in REQUIRED.items()
    }
    missing = {family: selectors for family, selectors in missing.items() if selectors}
    if missing:
        rows = [f"{family}: {', '.join(selectors)}" for family, selectors in missing.items()]
        raise SystemExit("INTERACTION_STATE_QSS_MISSING\n" + "\n".join(rows))

    composite_selectors = (
        "QComboBox > QLineEdit",
        "QSpinBox > QLineEdit",
        "QDoubleSpinBox > QLineEdit",
    )
    if any(selector not in qss for selector in composite_selectors):
        raise SystemExit("INTERACTION_STATE_QSS_MISSING composite_editor_reset")

    disabled_radio = (
        ROOT
        / "src"
        / "ida_modern_ui"
        / "themes"
        / "icons"
        / "radio_on_disabled.svg"
    )
    if not disabled_radio.is_file() or "@RADIO_ON_DISABLED_ICON@" not in qss:
        raise SystemExit("INTERACTION_STATE_QSS_MISSING muted_disabled_radio_asset")

    state_count = sum(len(selectors) for selectors in REQUIRED.values())
    print(
        "INTERACTION_STATE_QSS_OK "
        f"families={len(REQUIRED)} states={state_count} composite=single_frame"
    )


if __name__ == "__main__":
    main()
