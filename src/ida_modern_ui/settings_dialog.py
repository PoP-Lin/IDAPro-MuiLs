# -*- coding: utf-8 -*-
"""Live-preview settings dialog."""

from __future__ import annotations

from .config import DEFAULT_CONFIG
from .qt_compat import (
    QCheckBox,
    QColor,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    dialog_buttons,
    standard_button,
)


class SettingsDialog(QDialog):
    def __init__(self, config, preview_callback, parent=None):
        super().__init__(parent)
        self._preview_callback = preview_callback
        self.setWindowTitle("IDAPro-MuiLs Settings")
        self.setMinimumWidth(500)

        self.enabled = QCheckBox("Enable theme on IDA startup")
        self.smooth_resize = QCheckBox("Smooth window resizing")
        self.smooth_resize.setToolTip(
            "Defer workspace redraw while the outer window is being resized."
        )
        self.style_plugin_panels = QCheckBox("Style compatible Qt plugin panels")
        self.style_plugin_panels.setToolTip(
            "Apply scoped presentation roles without changing plugin layouts."
        )
        self.theme = QComboBox()
        self.theme.addItem("Modern Dark", "modern_dark")
        self.accent = QLineEdit()
        self.accent.setMaxLength(7)
        accent_button = QPushButton("Choose...")
        accent_button.clicked.connect(self._choose_accent)

        accent_row = QWidget()
        accent_layout = QHBoxLayout(accent_row)
        accent_layout.setContentsMargins(0, 0, 0, 0)
        accent_layout.addWidget(self.accent, 1)
        accent_layout.addWidget(accent_button)

        self.font_family = QLineEdit()
        self.code_font_family = QLineEdit()
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 16)
        self.font_size.setSuffix(" pt")
        self.corner_radius = QSpinBox()
        self.corner_radius.setRange(0, 14)
        self.corner_radius.setSuffix(" px")
        self.density = QComboBox()
        self.density.addItem("Comfortable", "comfortable")
        self.density.addItem("Compact", "compact")

        group = QGroupBox("Appearance")
        form = QFormLayout(group)
        form.setContentsMargins(12, 5, 12, 6)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(5)
        form.addRow(self.enabled)
        form.addRow(self.smooth_resize)
        form.addRow("Theme", self.theme)
        form.addRow("Accent", accent_row)
        form.addRow("Interface font", self.font_family)
        form.addRow("Code font", self.code_font_family)
        form.addRow("Font size", self.font_size)
        form.addRow("Corner radius", self.corner_radius)
        form.addRow("Density", self.density)

        plugin_group = QGroupBox("Plugin panels")
        plugin_layout = QVBoxLayout(plugin_group)
        plugin_layout.setContentsMargins(12, 5, 12, 6)
        plugin_layout.setSpacing(4)
        plugin_layout.addWidget(self.style_plugin_panels)
        plugin_note = QLabel(
            "Rounded cards and scoped colors; plugin layouts and local styles "
            "stay untouched."
        )
        plugin_note.setWordWrap(True)
        plugin_note.setObjectName("ModernUiHint")
        plugin_layout.addWidget(plugin_note)

        note = QLabel("Changes preview immediately. Cancel restores the last applied appearance.")
        note.setWordWrap(True)
        note.setObjectName("ModernUiHint")
        self.buttons = QDialogButtonBox(dialog_buttons())
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(standard_button("RestoreDefaults")).clicked.connect(
            self.restore_defaults
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 9, 14, 10)
        layout.setSpacing(7)
        layout.addWidget(group)
        layout.addWidget(plugin_group)
        layout.addWidget(note)
        layout.addWidget(self.buttons)

        self._load(config)
        self._connect_preview()

    def _connect_preview(self):
        controls = [
            self.enabled,
            self.smooth_resize,
            self.style_plugin_panels,
            self.theme,
            self.accent,
            self.font_family,
            self.code_font_family,
            self.font_size,
            self.corner_radius,
            self.density,
        ]
        for control in controls:
            if isinstance(control, QLineEdit):
                control.editingFinished.connect(self._preview)
            elif isinstance(control, QCheckBox):
                control.toggled.connect(self._preview)
            elif isinstance(control, QComboBox):
                control.currentIndexChanged.connect(self._preview)
            else:
                control.valueChanged.connect(self._preview)

    def _load(self, config):
        self.enabled.setChecked(config["enabled"])
        self.smooth_resize.setChecked(config["smooth_resize"])
        self.style_plugin_panels.setChecked(config["style_plugin_panels"])
        self.theme.setCurrentIndex(max(0, self.theme.findData(config["theme"])))
        self.accent.setText(config["accent"])
        self.font_family.setText(config["font_family"])
        self.code_font_family.setText(config["code_font_family"])
        self.font_size.setValue(config["font_size"])
        self.corner_radius.setValue(config["corner_radius"])
        self.density.setCurrentIndex(max(0, self.density.findData(config["density"])))

    def values(self):
        return {
            "enabled": self.enabled.isChecked(),
            "smooth_resize": self.smooth_resize.isChecked(),
            "style_plugin_panels": self.style_plugin_panels.isChecked(),
            "theme": self.theme.currentData(),
            "accent": self.accent.text(),
            "font_family": self.font_family.text().strip() or DEFAULT_CONFIG["font_family"],
            "code_font_family": self.code_font_family.text().strip()
            or DEFAULT_CONFIG["code_font_family"],
            "font_size": self.font_size.value(),
            "corner_radius": self.corner_radius.value(),
            "density": self.density.currentData(),
        }

    def restore_defaults(self):
        self._load(DEFAULT_CONFIG)
        self._preview()

    def _preview(self, *_):
        self._preview_callback(self.values())

    def _choose_accent(self):
        color = QColorDialog.getColor(QColor(self.accent.text()), self, "Choose accent color")
        if color.isValid():
            self.accent.setText(color.name().upper())
            self._preview()
