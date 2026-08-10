"""使用项目虚拟环境中的 PyInstaller 构建单文件 EXE。"""  # 说明本脚本只负责准备环境和执行打包。

from pathlib import Path  # 用统一的路径对象定位项目文件。
import subprocess  # 用于调用环境准备入口和 PyInstaller。
import sys  # 用于取得运行本脚本的 Python 解释器。

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # 从 scripts 目录向上定位项目根目录。
sys.path.insert(0, str(PROJECT_ROOT))  # 让构建脚本能够导入项目根目录中的共享信息包。
from version import APP_NAME  # 读取统一维护的应用名称，避免构建脚本重复定义。

SOURCE_ROOT = PROJECT_ROOT / "src"  # 指向需要加入模块搜索路径的源码目录。
MAIN_FILE = PROJECT_ROOT / "main.py"  # 指向程序的统一启动入口。
APP_ENTRY = SOURCE_ROOT / "main.py"  # 指向不包含开发环境检查的真正应用入口。
VENV_ROOT = PROJECT_ROOT / ".venv"  # 指向项目独立使用的虚拟环境目录。
VENV_PYTHON = VENV_ROOT / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")  # 定位虚拟环境解释器。


def main() -> int:  # 定义构建入口，并用整数表示最终退出状态。
    """准备项目环境并调用 PyInstaller。"""  # 概括构建函数承担的职责。
    subprocess.run(  # 先通过项目入口创建虚拟环境并同步依赖。
        [sys.executable, str(MAIN_FILE), "--setup-only"],  # 要求入口只准备环境而不启动 Qt 界面。
        cwd=PROJECT_ROOT,  # 固定工作目录，避免从其他目录执行时产生路径差异。
        check=True,  # 环境准备失败时立即抛出错误并停止构建。
    )  # 完成构建环境准备。

    pyinstaller_command = [  # 集中定义 PyInstaller 命令，便于查看和修改构建参数。
        str(VENV_PYTHON),  # 使用项目虚拟环境中的 Python。
        "-m",  # 让 Python 以模块方式启动后续工具。
        "PyInstaller",  # 调用虚拟环境中安装的 PyInstaller。
        "--name",  # 指定生成程序的名称。
        APP_NAME,  # 使用 version 包中统一定义的应用名称。
        "--windowed",  # 生成不显示命令行窗口的图形界面程序。
        "--onefile",  # 将应用及其依赖打包为单个可执行文件。
        "--noconfirm",  # 自动覆盖既有构建产物而不等待交互确认。
        "--paths",  # 声明额外的 Python 模块搜索路径。
        str(PROJECT_ROOT),  # 让 PyInstaller 能发现 src 和 version 两个项目包。
        "--specpath",  # 指定自动生成的 PyInstaller spec 文件目录。
        str(PROJECT_ROOT / "build"),  # 将 spec 文件也归入可清理的 build 目录。
        str(APP_ENTRY),  # 直接打包真正的应用入口，不把开发环境检查带入 EXE。
    ]  # 完成 PyInstaller 命令定义。

    subprocess.run(  # 执行已经定义好的 PyInstaller 构建命令。
        pyinstaller_command,  # 传入完整且不依赖终端解析的参数列表。
        cwd=PROJECT_ROOT,  # 固定构建工作目录为项目根目录。
        check=True,  # 构建失败时抛出错误，不再显示成功信息。
    )  # 等待 PyInstaller 构建结束。

    output = PROJECT_ROOT / "dist" / f"{APP_NAME}.exe"  # 根据统一应用名称计算 Windows EXE 的预期位置。
    print(f"构建完成：{output}")  # 向开发者显示最终构建产物路径。
    return 0  # 用零退出码表示构建成功。


if __name__ == "__main__":  # 仅在直接运行本脚本时开始构建。
    raise SystemExit(main())  # 执行构建入口并把返回值作为进程退出码。
