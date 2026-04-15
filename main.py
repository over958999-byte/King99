import sys
import os

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from utils.config_loader import load_config
from gui.main_window import MainWindow
from gui.style import get_stylesheet


def main() -> None:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    config = load_config()

    app = QApplication(sys.argv)
    app.setApplicationName("困King落地助手")
    app.setStyleSheet(get_stylesheet())
    app.setFont(QFont("Microsoft YaHei UI", 10))

    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
