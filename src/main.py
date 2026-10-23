"""创建桌面应用，先建立用户目录和日志，再显式装配功能。"""

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from src.app.bootstrap import create_main_window
from src.shared.theme import ThemeManager
from src.shared.logging_service import LoggingService
from src.shared.paths import UserPaths
from version import APP_ID, APP_NAME, APP_VERSION


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    themes = ThemeManager(app)
    logs = None
    try:
        paths = UserPaths.discover()
        paths.ensure()
        logs = LoggingService(paths.logs)
        logging.getLogger("workbench.app").info("应用启动，版本 %s", APP_VERSION)
        logging.getLogger("workbench.app").info("用户目录就绪：配置=%s，数据=%s，缓存=%s，日志=%s", paths.config, paths.data, paths.cache, paths.logs)
        window = create_main_window(paths, logs, themes)
    except Exception as error:
        logging.getLogger("workbench.app").exception("应用初始化失败")
        if logs:
            logs.stop()
        dialog = QMessageBox()
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle("无法启动")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f"初始化失败，未覆盖原配置。\n{error}")
        dialog.exec()
        return 1
    window.show()
    try:
        return app.exec()
    finally:
        logging.getLogger("workbench.app").info("应用退出")
        logs.stop()


if __name__ == "__main__":
    raise SystemExit(main())
