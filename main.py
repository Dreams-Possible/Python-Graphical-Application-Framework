"""检查项目运行环境，然后启动 src 中真正的 Qt 应用。"""  # 说明本文件只负责环境准备和应用转交。

from pathlib import Path  # 用统一的路径对象处理 Windows 和其他系统的路径。
import subprocess  # 用于安装依赖并切换到虚拟环境中的 Python。
import sys  # 用于读取当前解释器、命令行参数和模块搜索路径。
import venv  # 使用 Python 自带能力创建项目虚拟环境。


PROJECT_ROOT = Path(__file__).resolve().parent  # 取得当前项目的根目录。
SOURCE_ROOT = PROJECT_ROOT / "src"  # 指向存放真正应用源码的目录。
VENV_ROOT = PROJECT_ROOT / ".venv"  # 指向项目独立使用的虚拟环境目录。
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"  # 指向项目依赖清单。
VENV_PYTHON = VENV_ROOT / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")  # 定位虚拟环境解释器。


def main() -> int:  # 定义程序入口，并用整数表示最终退出状态。
    """准备运行环境并启动真正的应用入口。"""  # 概括入口函数承担的职责。
    is_project_python = Path(sys.executable).resolve() == VENV_PYTHON.resolve()  # 判断是否已在项目虚拟环境中运行。

    if not is_project_python:  # 尚未切换到项目解释器时准备开发环境。
        if not VENV_PYTHON.is_file():  # 只在虚拟环境不存在时创建它。
            print(f"[environment] 创建虚拟环境：{VENV_ROOT}")  # 向开发者显示当前环境准备进度。
            venv.create(VENV_ROOT, with_pip=True)  # 创建虚拟环境并同时安装 pip。

        print("[environment] 同步项目依赖...")  # 告知开发者即将根据依赖清单安装依赖。
        subprocess.run(  # 调用虚拟环境中的 pip 同步项目依赖。
            [str(VENV_PYTHON), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],  # 组合不依赖终端类型的安装命令。
            check=True,  # 安装失败时立即抛出错误并停止启动。
        )  # 完成依赖同步。
        command = [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]]  # 保留原参数并改用项目解释器重新启动。
        return subprocess.call(command)  # 等待重新启动的进程结束并传回其退出状态。

    if "--setup-only" in sys.argv:  # 构建脚本可要求只完成环境准备而不打开界面。
        return 0  # 向构建脚本报告环境已经准备完成。

    sys.path.insert(0, str(PROJECT_ROOT))  # 让 Python 能从项目根目录导入 src 应用包。
    from src.main import main as run_application  # 延迟导入，确保依赖和模块路径已经准备完毕。

    return run_application()  # 将程序控制权交给真正的 Qt 应用入口。


if __name__ == "__main__":  # 仅在直接运行本文件时启动程序。
    raise SystemExit(main())  # 执行入口并把返回值作为进程退出码。
