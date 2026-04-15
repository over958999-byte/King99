import sys
import os

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFont

from utils.config_loader import load_config
from gui.main_window import MainWindow
from gui.style import get_stylesheet


def _verify_authorization(app: QApplication) -> bool:
    """启动前验证 GitHub 仓库是否可访问，不可访问则弹窗退出。"""
    from utils.updater import verify_repo

    result = verify_repo()
    if result["ok"]:
        return True

    if result["reason"] == "not_found":
        QMessageBox.critical(None, "授权验证失败", "授权已失效，软件无法运行。")
    else:
        QMessageBox.critical(None, "授权验证失败", "无法验证授权，请检查网络连接。")
    return False


def main() -> None:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    config = load_config()

    app = QApplication(sys.argv)
    app.setApplicationName("困King落地助手")
    app.setStyleSheet(get_stylesheet())
    app.setFont(QFont("Microsoft YaHei UI", 10))

    if not _verify_authorization(app):
        sys.exit(1)

    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
