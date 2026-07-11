# =============================================================================
#  Program Inventory — dark-industrial palette and stylesheet
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================
# --- Dark-industrial palette -------------------------------------------------
OBSIDIAN = "#0b0f14"
STEEL    = "#232b35"
STEEL_HI = "#2c3642"
TEAL     = "#2fd6c3"
PHOSPHOR = "#4be08a"
AMBER    = "#ffb454"
RED      = "#ff5c66"
TEXT     = "#d7e0ea"
TEXT_DIM = "#7a8794"
MONO     = "JetBrains Mono"

QSS = f"""
* {{ font-family: '{MONO}', 'Consolas', monospace; font-size: 12px; }}
QMainWindow, QDialog {{ background: {OBSIDIAN}; }}
QWidget {{ color: {TEXT}; }}
QLabel#Header {{ color: {TEAL}; font-size: 16px; font-weight: bold; letter-spacing: 2px; }}
QLabel#SubHeader {{ color: {TEXT_DIM}; font-size: 11px; letter-spacing: 1px; }}
QLabel.chip {{
    background: {STEEL}; color: {TEXT}; padding: 4px 10px;
    border: 1px solid {STEEL_HI}; border-radius: 0px;
}}
QLabel.chipOk    {{ color: {PHOSPHOR}; }}
QLabel.chipWarn  {{ color: {AMBER}; }}
QLabel.chipErr   {{ color: {RED}; }}
QPushButton {{
    background: {STEEL}; color: {TEXT}; border: 1px solid {STEEL_HI};
    padding: 7px 16px; border-radius: 0px; font-weight: bold;
}}
QPushButton:hover  {{ border-color: {TEAL}; color: {TEAL}; }}
QPushButton:pressed {{ background: {OBSIDIAN}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; border-color: {STEEL}; }}
QPushButton#Primary {{ border-color: {TEAL}; color: {TEAL}; }}
QPushButton#Primary:hover {{ background: {TEAL}; color: {OBSIDIAN}; }}
QPushButton#Danger:hover {{ border-color: {RED}; color: {RED}; }}
QPushButton:checked {{ background: {AMBER}; color: {OBSIDIAN}; border-color: {AMBER}; }}
QLineEdit, QComboBox {{
    background: {STEEL}; color: {TEXT}; border: 1px solid {STEEL_HI};
    padding: 6px 10px; border-radius: 0px; selection-background-color: {TEAL};
    selection-color: {OBSIDIAN};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {TEAL}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {STEEL}; color: {TEXT}; border: 1px solid {TEAL};
    selection-background-color: {TEAL}; selection-color: {OBSIDIAN};
    outline: none;
}}
QTableView {{
    background: {OBSIDIAN}; alternate-background-color: #10161d;
    color: {TEXT}; gridline-color: {STEEL};
    border: 1px solid {STEEL_HI}; border-radius: 0px;
    selection-background-color: {STEEL_HI}; selection-color: {TEAL};
}}
QHeaderView::section {{
    background: {STEEL}; color: {TEAL}; border: none;
    border-right: 1px solid {OBSIDIAN}; border-bottom: 1px solid {TEAL};
    padding: 6px 8px; font-weight: bold;
}}
QPlainTextEdit {{
    background: #10161d; color: {TEXT}; border: 1px solid {STEEL_HI};
    border-radius: 0px; selection-background-color: {TEAL};
    selection-color: {OBSIDIAN};
}}
QMenu {{ background: {STEEL}; color: {TEXT}; border: 1px solid {TEAL}; }}
QMenu::item {{ padding: 6px 24px; }}
QMenu::item:selected {{ background: {TEAL}; color: {OBSIDIAN}; }}
QScrollBar:vertical {{ background: {OBSIDIAN}; width: 12px; }}
QScrollBar::handle:vertical {{ background: {STEEL_HI}; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {TEAL}; }}
QScrollBar:horizontal {{ background: {OBSIDIAN}; height: 12px; }}
QScrollBar::handle:horizontal {{ background: {STEEL_HI}; min-width: 24px; }}
QScrollBar::handle:horizontal:hover {{ background: {TEAL}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QSplitter::handle {{ background: {STEEL}; }}
"""

