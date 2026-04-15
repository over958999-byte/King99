"""全局 QSS 样式表 -- 现代蓝白商务风格（精美版 v2）。"""

# 配色常量
PRIMARY = "#2563EB"
PRIMARY_DARK = "#1D4ED8"
PRIMARY_DARKER = "#1E40AF"
PRIMARY_LIGHT = "#DBEAFE"
PRIMARY_LIGHTER = "#EFF6FF"
BG_WHITE = "#FFFFFF"
BG_SECONDARY = "#F8FAFC"
BG_CARD = "#FAFBFC"
BG_HOVER = "#F1F5F9"
BORDER = "#E2E8F0"
BORDER_LIGHT = "#F1F5F9"
BORDER_FOCUS = "#93C5FD"
TEXT_PRIMARY = "#1E293B"
TEXT_SECONDARY = "#64748B"
TEXT_HINT = "#94A3B8"
SUCCESS = "#10B981"
SUCCESS_DARK = "#059669"
SUCCESS_LIGHT = "#ECFDF5"
DANGER = "#EF4444"
DANGER_DARK = "#DC2626"
DANGER_LIGHT = "#FEF2F2"
WARNING = "#F59E0B"
WARNING_LIGHT = "#FFFBEB"
INFO = "#3B82F6"
INFO_LIGHT = "#EFF6FF"
SHADOW = "rgba(0, 0, 0, 0.04)"
SHADOW_MEDIUM = "rgba(0, 0, 0, 0.08)"


def get_stylesheet() -> str:
    return f"""
    /* ========== 全局基础 ========== */
    QMainWindow, QWidget {{
        background-color: {BG_SECONDARY};
        color: {TEXT_PRIMARY};
        font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
    }}

    /* ========== QTabWidget ========== */
    QTabWidget::pane {{
        border: 1px solid {BORDER};
        border-top: none;
        background: {BG_WHITE};
        border-bottom-left-radius: 8px;
        border-bottom-right-radius: 8px;
    }}
    QTabBar::tab {{
        background: {BG_SECONDARY};
        color: {TEXT_SECONDARY};
        border: 1px solid {BORDER};
        border-bottom: none;
        padding: 10px 24px;
        margin-right: 2px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        font-size: 13px;
        font-weight: 500;
    }}
    QTabBar::tab:selected {{
        background: {BG_WHITE};
        color: {PRIMARY};
        font-weight: bold;
        border-bottom: 3px solid {PRIMARY};
        padding-bottom: 8px;
    }}
    QTabBar::tab:hover:!selected {{
        background: {PRIMARY_LIGHTER};
        color: {PRIMARY};
    }}

    /* ========== QPushButton 基础 ========== */
    QPushButton {{
        background-color: {BG_WHITE};
        color: {PRIMARY};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 16px;
        font-size: 12px;
        font-weight: 500;
        min-height: 26px;
    }}
    QPushButton:hover {{
        background-color: {PRIMARY_LIGHTER};
        border-color: {PRIMARY};
        color: {PRIMARY_DARK};
    }}
    QPushButton:pressed {{
        background-color: {PRIMARY_LIGHT};
        border-color: {PRIMARY_DARK};
        color: {PRIMARY_DARK};
    }}
    QPushButton:disabled {{
        background-color: {BG_SECONDARY};
        color: {TEXT_HINT};
        border-color: {BORDER_LIGHT};
    }}

    /* 主要操作按钮 */
    QPushButton[class="primary"] {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {PRIMARY}, stop:1 {PRIMARY_DARK});
        color: {BG_WHITE};
        border: 1px solid {PRIMARY_DARK};
        font-weight: bold;
        border-radius: 6px;
    }}
    QPushButton[class="primary"]:hover {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {PRIMARY_DARK}, stop:1 {PRIMARY_DARKER});
        border-color: {PRIMARY_DARKER};
    }}
    QPushButton[class="primary"]:pressed {{
        background-color: {PRIMARY_DARKER};
    }}
    QPushButton[class="primary"]:disabled {{
        background-color: #90CAF9;
        border-color: #90CAF9;
        color: rgba(255, 255, 255, 0.7);
    }}

    /* 危险操作按钮 */
    QPushButton[class="danger"] {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {DANGER}, stop:1 {DANGER_DARK});
        color: {BG_WHITE};
        border: 1px solid {DANGER_DARK};
        border-radius: 6px;
    }}
    QPushButton[class="danger"]:hover {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {DANGER_DARK}, stop:1 #B91C1C);
        border-color: #B91C1C;
    }}
    QPushButton[class="danger"]:pressed {{
        background-color: #B91C1C;
    }}
    QPushButton[class="danger"]:disabled {{
        background-color: #FCA5A5;
        border-color: #FCA5A5;
        color: rgba(255, 255, 255, 0.7);
    }}

    /* ========== QTableWidget ========== */
    QTableWidget {{
        background-color: {BG_WHITE};
        alternate-background-color: #F8FAFC;
        border: 1px solid {BORDER};
        gridline-color: {BORDER_LIGHT};
        selection-background-color: {PRIMARY_LIGHT};
        selection-color: {TEXT_PRIMARY};
        border-radius: 8px;
        font-size: 12px;
        outline: none;
    }}
    QTableWidget::item {{
        padding: 6px 8px;
        border-bottom: 1px solid {BORDER_LIGHT};
    }}
    QTableWidget::item:selected {{
        background-color: {PRIMARY_LIGHT};
        color: {TEXT_PRIMARY};
    }}
    QHeaderView::section {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F8FAFC, stop:1 #EDF2F7);
        color: {TEXT_SECONDARY};
        padding: 8px 10px;
        border: none;
        border-right: 1px solid {BORDER_LIGHT};
        border-bottom: 2px solid {PRIMARY};
        font-weight: 600;
        font-size: 12px;
    }}
    QHeaderView::section:last {{
        border-right: none;
    }}

    /* ========== QListWidget ========== */
    QListWidget {{
        background-color: {BG_WHITE};
        border: 1px solid {BORDER};
        border-radius: 6px;
        font-size: 12px;
        outline: none;
        padding: 2px;
    }}
    QListWidget::item {{
        padding: 5px 10px;
        border-bottom: 1px solid {BORDER_LIGHT};
        border-radius: 4px;
        margin: 1px 2px;
    }}
    QListWidget::item:last {{
        border-bottom: none;
    }}
    QListWidget::item:hover {{
        background-color: {PRIMARY_LIGHTER};
    }}
    QListWidget::item:selected {{
        background-color: {PRIMARY_LIGHT};
        color: {TEXT_PRIMARY};
    }}

    /* ========== QComboBox ========== */
    QComboBox {{
        background-color: {BG_WHITE};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 5px 10px;
        min-height: 26px;
        font-size: 12px;
        color: {TEXT_PRIMARY};
    }}
    QComboBox:hover {{
        border-color: {BORDER_FOCUS};
    }}
    QComboBox:focus {{
        border-color: {PRIMARY};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 28px;
        border-left: 1px solid {BORDER_LIGHT};
        border-top-right-radius: 6px;
        border-bottom-right-radius: 6px;
        background: {BG_SECONDARY};
    }}
    QComboBox::down-arrow {{
        width: 10px;
        height: 10px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {BG_WHITE};
        border: 1px solid {BORDER};
        border-radius: 6px;
        selection-background-color: {PRIMARY_LIGHT};
        selection-color: {TEXT_PRIMARY};
        outline: none;
        padding: 4px;
    }}

    /* ========== QLineEdit / QPlainTextEdit / QTextEdit ========== */
    QLineEdit, QPlainTextEdit, QTextEdit {{
        background-color: {BG_WHITE};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 5px 10px;
        font-size: 12px;
        color: {TEXT_PRIMARY};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border-color: {PRIMARY};
    }}
    QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {{
        border-color: {BORDER_FOCUS};
    }}

    /* ========== QSpinBox ========== */
    QSpinBox {{
        background-color: {BG_WHITE};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 5px 10px;
        min-height: 26px;
        font-size: 12px;
        color: {TEXT_PRIMARY};
    }}
    QSpinBox:focus {{
        border-color: {PRIMARY};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        width: 22px;
        background: {BG_SECONDARY};
        border: none;
        border-radius: 3px;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
        background: {PRIMARY_LIGHT};
    }}

    /* ========== QGroupBox ========== */
    QGroupBox {{
        font-weight: 600;
        font-size: 13px;
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: 8px;
        margin-top: 14px;
        padding-top: 20px;
        background-color: {BG_WHITE};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 14px;
        padding: 2px 10px;
        background-color: {BG_WHITE};
        color: {PRIMARY};
        border-radius: 4px;
    }}

    /* ========== QLabel ========== */
    QLabel {{
        color: {TEXT_PRIMARY};
        font-size: 12px;
    }}

    /* ========== QCheckBox ========== */
    QCheckBox {{
        spacing: 8px;
        font-size: 12px;
        color: {TEXT_PRIMARY};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1.5px solid {BORDER};
        border-radius: 4px;
        background: {BG_WHITE};
    }}
    QCheckBox::indicator:checked {{
        background-color: {PRIMARY};
        border-color: {PRIMARY};
    }}
    QCheckBox::indicator:hover {{
        border-color: {PRIMARY};
    }}

    /* ========== QScrollBar (vertical) ========== */
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 2px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: #CBD5E1;
        min-height: 30px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #94A3B8;
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: none;
    }}

    /* ========== QScrollBar (horizontal) ========== */
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
        margin: 2px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: #CBD5E1;
        min-width: 30px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: #94A3B8;
    }}
    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {{
        background: none;
    }}

    /* ========== QStatusBar ========== */
    QStatusBar {{
        background-color: {BG_WHITE};
        border-top: 1px solid {BORDER_LIGHT};
        color: {TEXT_SECONDARY};
        font-size: 12px;
        padding: 4px 12px;
    }}

    /* ========== QMessageBox ========== */
    QMessageBox {{
        background-color: {BG_WHITE};
    }}
    QMessageBox QPushButton {{
        min-width: 80px;
        padding: 8px 20px;
    }}

    /* ========== QDialog ========== */
    QDialog {{
        background-color: {BG_WHITE};
    }}

    /* ========== QDialogButtonBox ========== */
    QDialogButtonBox QPushButton {{
        min-width: 80px;
        padding: 8px 20px;
    }}

    /* ========== QFormLayout labels ========== */
    QFormLayout QLabel {{
        font-weight: normal;
        color: {TEXT_SECONDARY};
        font-size: 12px;
    }}

    /* ========== QSplitter ========== */
    QSplitter::handle {{
        background: {BORDER_LIGHT};
    }}
    QSplitter::handle:horizontal {{
        width: 3px;
    }}
    QSplitter::handle:vertical {{
        height: 3px;
    }}
    QSplitter::handle:hover {{
        background: {PRIMARY};
    }}

    /* ========== QToolTip ========== */
    QToolTip {{
        background-color: #1E293B;
        color: {BG_WHITE};
        border: none;
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 12px;
    }}

    /* ========== QProgressBar ========== */
    QProgressBar {{
        background-color: #E2E8F0;
        border: none;
        border-radius: 10px;
        text-align: center;
        font-size: 11px;
        font-weight: 600;
        color: {TEXT_SECONDARY};
        min-height: 20px;
    }}
    QProgressBar::chunk {{
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {PRIMARY}, stop:1 #60A5FA);
        border-radius: 10px;
    }}

    /* ========== 筛选按钮（可选中状态） ========== */
    QPushButton[checkable="true"] {{
        background-color: {BG_WHITE};
        color: {TEXT_SECONDARY};
        border: 1px solid {BORDER};
        border-radius: 14px;
        padding: 3px 14px;
        font-size: 11px;
        font-weight: 500;
        min-height: 22px;
    }}
    QPushButton[checkable="true"]:hover {{
        background-color: {PRIMARY_LIGHTER};
        border-color: {BORDER_FOCUS};
        color: {PRIMARY};
    }}
    QPushButton[checkable="true"]:checked {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {PRIMARY}, stop:1 {PRIMARY_DARK});
        color: {BG_WHITE};
        border-color: {PRIMARY_DARK};
        font-weight: bold;
    }}

    /* ========== CollapsibleGroupBox ========== */
    QGroupBox::indicator {{
        width: 14px;
        height: 14px;
        border: 1.5px solid {BORDER};
        border-radius: 4px;
        background: {BG_WHITE};
    }}
    QGroupBox::indicator:checked {{
        background-color: {PRIMARY};
        border-color: {PRIMARY};
    }}
    QGroupBox::indicator:unchecked {{
        background-color: {BG_SECONDARY};
        border-color: {BORDER};
    }}
    """
