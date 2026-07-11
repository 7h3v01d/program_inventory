# ruff: noqa: F401  — this module exists to re-export Qt names
# =============================================================================
#  Program Inventory — Qt binding shim: PySide6 preferred, PyQt6 fallback
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================

# --- Qt binding shim: PySide6 first (installed binding), PyQt6 fallback -----
try:
    from PySide6.QtCore import (Qt, QObject, QThread, Signal, Slot,
                                QSortFilterProxyModel, QModelIndex)
    from PySide6.QtGui import QStandardItemModel, QStandardItem, QFont, QColor
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QLineEdit, QComboBox, QTableView, QHeaderView, QMenu,
        QPlainTextEdit, QFileDialog, QMessageBox, QDialog, QSplitter,
        QAbstractItemView,
    )
    QT_BINDING = "PySide6"
except ImportError:
    from PyQt6.QtCore import (Qt, QObject, QThread, pyqtSignal as Signal,  # type: ignore
                              pyqtSlot as Slot, QSortFilterProxyModel, QModelIndex)
    from PyQt6.QtGui import QStandardItemModel, QStandardItem, QFont, QColor  # type: ignore
    from PyQt6.QtWidgets import (                                          # type: ignore
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QLineEdit, QComboBox, QTableView, QHeaderView, QMenu,
        QPlainTextEdit, QFileDialog, QMessageBox, QDialog, QSplitter,
        QAbstractItemView,
    )
    QT_BINDING = "PyQt6"

