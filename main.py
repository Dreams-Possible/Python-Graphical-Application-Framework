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


def has_working_pip() -> bool:  # 检查虚拟环境是否不仅存在，而且能够正常调用 pip。
    """返回项目虚拟环境中的 pip 是否可用。"""  # 避免把残缺的虚拟环境误判为已经准备完成。
    try:  # 已存在的解释器仍可能因虚拟环境损坏而无法启动。
        result = subprocess.run(  # 用实际命令验证 pip 模块，而不只检查某个脚本文件。
            [str(VENV_PYTHON), "-m", "pip", "--version"],  # 要求虚拟环境解释器导入并运行 pip。
            stdout=subprocess.DEVNULL,  # 正常检查时不输出无关版本信息。
            stderr=subprocess.DEVNULL,  # 检查失败时由后续修复提示统一说明。
            check=False,  # 根据返回码判断完整性，不在这里中断程序。
        )  # 完成 pip 可用性探测。
    except OSError:  # 解释器文件存在但已经无法执行时也视为环境不完整。
        return False  # 交由 venv 使用当前系统解释器尝试修复。

    return result.returncode == 0  # 只有 pip 命令成功才认为虚拟环境完整。


def ensure_virtual_environment() -> None:  # 创建新环境，或补齐缺少解释器、pip 的残缺环境。
    """确保项目虚拟环境包含可工作的 Python 和 pip。"""  # 集中管理跨平台环境完整性检查。
    if not VENV_PYTHON.is_file():  # 首次运行或缺少解释器时需要创建完整环境。
        print(f"[environment] 创建虚拟环境：{VENV_ROOT}")  # 明确告知开发者当前动作。
        venv.create(VENV_ROOT, with_pip=True)  # 使用当前平台 Python 创建解释器、激活脚本和 pip。
    elif not has_working_pip():  # 解释器存在但 pip 模块缺失时原地修复，保留已有依赖。
        print(f"[environment] 修复虚拟环境中的 pip：{VENV_ROOT}")  # 明确说明修复对象和原因。
        subprocess.run(  # Python 标准库 ensurepip 可恢复 venv 中缺失的 pip。
            [str(VENV_PYTHON), "-m", "ensurepip", "--upgrade"],  # 安装或更新该环境自己的 pip。
            check=True,  # 修复失败时立即停止，避免继续使用残缺环境。
        )  # 完成 pip 原地修复。

    subprocess.run(  # 修复后再次执行真实命令，确保问题能够被明确暴露。
        [str(VENV_PYTHON), "-m", "pip", "--version"],  # 验证后续依赖安装所需的 pip 模块。
        stdout=subprocess.DEVNULL,  # 验证成功时保持启动输出简洁。
        check=True,  # 修复后仍不可用时立即停止，不继续进入半完整环境。
    )  # 完成虚拟环境完整性确认。


def main() -> int:  # 定义程序入口，并用整数表示最终退出状态。
    """准备运行环境并启动真正的应用入口。"""  # 概括入口函数承担的职责。
    is_project_python = Path(sys.executable).resolve() == VENV_PYTHON.resolve()  # 判断是否已在项目虚拟环境中运行。
    ensure_virtual_environment()  # 无论从系统还是项目解释器启动，都先确认 Python 和 pip 完整。

    if not is_project_python:  # 尚未切换到项目解释器时准备开发环境。
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
