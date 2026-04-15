import os
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QFileDialog,
)
from PySide6.QtCore import Slot


class LogTab(QWidget):
    """日志标签页：显示操作日志，支持清空和导出。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 顶部按钮栏
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        btn_layout.addStretch()
        self.clear_btn = QPushButton("清空日志")
        self.export_btn = QPushButton("导出日志")
        self.export_btn.setProperty("class", "primary")
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addWidget(self.export_btn)
        layout.addLayout(btn_layout)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "QTextEdit {"
            "  font-family: Consolas, 'Cascadia Code', 'Courier New', monospace;"
            "  font-size: 12px;"
            "  line-height: 1.5;"
            "  padding: 8px;"
            "  background-color: #FAFBFC;"
            "  border: 1px solid #E2E8F0;"
            "  border-radius: 6px;"
            "}"
        )
        layout.addWidget(self.log_text)

        self.clear_btn.clicked.connect(self._clear_log)
        self.export_btn.clicked.connect(self._export_log)

    @Slot(str)
    def append_log(self, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def _clear_log(self):
        self.log_text.clear()

    def _export_log(self):
        default_name = f"detection_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", default_name, "文本文件 (*.txt);;所有文件 (*)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_text.toPlainText())
