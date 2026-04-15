import sys
import os

from PySide6.QtWidgets import QApplication, QMessageBox
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

    # 验证仓库授权
    import requests
    try:
        resp = requests.get("https://api.github.com/repos/over958999-byte/King99", timeout=10)
        if resp.status_code == 404:
            QMessageBox.critical(None, "错误", "授权已失效，软件无法运行")
            sys.exit(1)
        elif resp.status_code != 200:
            QMessageBox.critical(None, "错误", "授权验证失败，软件无法运行")
            sys.exit(1)
    except Exception:
        QMessageBox.critical(None, "错误", "无法验证授权，请检查网络连接")
        sys.exit(1)

    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
