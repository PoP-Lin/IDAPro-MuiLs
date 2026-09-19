# -*- coding: utf-8 -*-
"""Small compatibility surface for IDA builds using PySide6 or PyQt5."""

try:
    from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, QTimer, Qt
    from PySide6.QtGui import (
        QBrush,
        QColor,
        QCursor,
        QFontDatabase,
        QIcon,
        QPainter,
        QPainterPath,
        QPen,
        QRegion,
    )
    from PySide6.QtWidgets import (
        QAbstractButton,
        QApplication,
        QCheckBox,
        QColorDialog,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMenu,
        QMenuBar,
        QPushButton,
        QSlider,
        QSpinBox,
        QSplitter,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    from PyQt5.QtCore import QEvent, QObject, QPointF, QRectF, QSize, QTimer, Qt
    from PyQt5.QtGui import (
        QBrush,
        QColor,
        QCursor,
        QFontDatabase,
        QIcon,
        QPainter,
        QPainterPath,
        QPen,
        QRegion,
    )
    from PyQt5.QtWidgets import (
        QAbstractButton,
        QApplication,
        QCheckBox,
        QColorDialog,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMenu,
        QMenuBar,
        QPushButton,
        QSlider,
        QSpinBox,
        QSplitter,
        QVBoxLayout,
        QWidget,
    )


def horizontal_orientation():
    if hasattr(Qt, "Horizontal"):
        return Qt.Horizontal
    return Qt.Orientation.Horizontal


def vertical_orientation():
    if hasattr(Qt, "Vertical"):
        return Qt.Vertical
    return Qt.Orientation.Vertical


def dialog_buttons():
    standard = getattr(QDialogButtonBox, "StandardButton", QDialogButtonBox)
    return standard.Ok | standard.Cancel | standard.Apply | standard.RestoreDefaults


def standard_button(name):
    standard = getattr(QDialogButtonBox, "StandardButton", QDialogButtonBox)
    return getattr(standard, name)


def qobject_key(value):
    """Return a stable C++ identity across recreated PySide/PyQt wrappers."""
    if value is None:
        return None
    try:
        import shiboken6

        # PySide 6.8 can access-violate instead of raising when getCppPointer()
        # receives a wrapper whose C++ QObject is already being destroyed.
        if not shiboken6.isValid(value):
            return ("python", id(value))
        pointer = shiboken6.getCppPointer(value)
        if pointer:
            return ("cpp", int(pointer[0]))
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass
    try:
        import sip

        return ("cpp", int(sip.unwrapinstance(value)))
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        return ("python", id(value))


def same_qobject(left, right):
    return left is right or (
        left is not None and right is not None and qobject_key(left) == qobject_key(right)
    )


def dialog_accepted():
    if hasattr(QDialog, "Accepted"):
        return QDialog.Accepted
    return QDialog.DialogCode.Accepted


def execute_dialog(dialog):
    if hasattr(dialog, "exec"):
        return dialog.exec()
    return dialog.exec_()
