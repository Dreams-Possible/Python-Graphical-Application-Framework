"""一次性清理项目中能够重新生成的构建文件。"""  # 说明本脚本不会删除源码和虚拟环境。

from pathlib import Path  # 用统一的路径对象查找待清理文件。
import shutil  # 用于递归删除非空的构建目录。


PROJECT_ROOT = Path(__file__).resolve().parent.parent  # 从 scripts 目录向上定位项目根目录。
VENV_ROOT = PROJECT_ROOT / ".venv"  # 标记不能被清理脚本修改的虚拟环境目录。
BUILD_DIRECTORIES = ("build", "dist", "__pycache__")  # 定义允许删除的构建目录名称。


def main() -> int:  # 定义清理入口，并用整数表示最终退出状态。
    """删除构建目录、Python 缓存和 PyInstaller spec 文件。"""  # 概括清理函数承担的职责。
    directories = [  # 先完整收集目标，避免边遍历边删除导致路径失效。
        path  # 保留当前符合条件的目录路径。
        for path in PROJECT_ROOT.rglob("*")  # 遍历项目中的所有文件和目录。
        if path.is_dir()  # 只选择目录而不处理普通文件。
        and path.name in BUILD_DIRECTORIES  # 只选择名称明确列出的可再生成目录。
        and VENV_ROOT not in path.parents  # 明确排除虚拟环境内部的缓存目录。
    ]  # 完成全部待清理目录的收集。

    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):  # 从最深层开始安全删除目标目录。
        shutil.rmtree(directory)  # 递归删除当前构建目录及其全部内容。
        print(f"已删除：{directory}")  # 向开发者显示刚刚清理的目录。

    for spec_file in PROJECT_ROOT.glob("*.spec"):  # 查找可能遗留在项目根目录的 PyInstaller 配置文件。
        spec_file.unlink()  # 删除能够由构建脚本重新生成的 spec 文件。
        print(f"已删除：{spec_file}")  # 向开发者显示刚刚清理的文件。

    print("清理完成。")  # 告知开发者所有目标均已处理完毕。
    return 0  # 用零退出码表示清理成功。


if __name__ == "__main__":  # 仅在直接运行本脚本时开始清理。
    raise SystemExit(main())  # 执行清理入口并把返回值作为进程退出码。
