"""创建并运行真正的 Qt 图形界面应用。"""  # 说明本文件是应用本身的运行入口。

import sys  # 用于把启动程序时收到的命令行参数交给 Qt。

from PySide6.QtWidgets import QApplication  # 导入 Qt 应用对象，负责事件循环和应用生命周期。

from src.app.bootstrap import create_main_window  # 导入顶层装配函数，用它创建完整的主窗口。
from version import APP_NAME, APP_VERSION  # 导入统一维护的应用名称和版本号。


def main() -> int:  # 定义真正的应用入口，并返回 Qt 的退出状态。
    """创建 Qt 应用、显示主窗口并进入事件循环。"""  # 概括应用启动过程。
    app = QApplication(sys.argv)  # 创建全局唯一的 Qt 应用对象并接收命令行参数。
    app.setApplicationName(APP_NAME)  # 设置操作系统和 Qt 能识别的应用名称。
    app.setApplicationVersion(APP_VERSION)  # 把统一版本号注册到 Qt 应用元数据中。

    window = create_main_window()  # 创建主窗口并在装配过程中连接它所依赖的对象。
    window.show()  # 显示主窗口；创建窗口本身不会自动显示它。

    return app.exec()  # 启动 Qt 事件循环，并在应用退出时返回退出码。


if __name__ == "__main__":  # 仅在直接执行本文件时启动应用。
    raise SystemExit(main())  # 运行应用，并把 Qt 的返回值作为进程退出码。
