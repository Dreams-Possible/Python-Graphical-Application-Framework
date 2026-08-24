# Python Graphical Application Framework

一个以功能模块化、单向数据流和 Qt 原生运行机制为基础的跨平台 Python 图形应用 Demo。Demo 面向 Windows、macOS 和 Linux，同时允许后续项目按需增加平台专用实现，不强制所有功能在每个平台保持一致。

## 当前 Demo

当前示例只包含一个计数器功能，用最少代码展示：

- `features/counter/` 集中保存一个完整功能；
- `CounterState` 是不可变页面状态；
- `CounterViewModel` 接收用户操作并通过 Qt Signal 公开状态；
- `CounterView` 只渲染状态并转发用户操作；
- `app/bootstrap.py` 负责显式创建和连接对象；
- PyInstaller 按当前系统生成可发布的 Windows、macOS 或 Linux 桌面程序。

## 目录结构

```text
项目根目录/
├── main.py                 # 环境自检查，并启动真正的应用入口
├── requirements.txt       # 运行与打包依赖
├── src/                   # 应用源码
│   ├── main.py            # 真正的 Qt 应用入口
│   ├── app/               # 应用装配
│   └── features/          # 功能模块
├── version/               # 应用名称与版本信息
├── scripts/
│   ├── build.py           # PyInstaller 构建脚本
│   └── clean.py           # 构建产物清理脚本
├── docs/                  # 设计文档
└── .gitignore
```

## 初始化开发环境

先确保 Windows 能够执行 `python`，或 macOS/Linux 能够执行 `python3`。第一次运行主入口即可。

Windows：

```text
python main.py
```

macOS/Linux：

```text
python3 main.py
```

根入口会使用 Python 标准库 `venv` 创建 `.venv`、安装 `requirements.txt`，再自动使用虚拟环境中的 Python 启动真正的 Qt 应用。

## 调试运行

Windows 使用 `python main.py`，macOS/Linux 使用 `python3 main.py`。

Windows 下 IDE 的 Python 解释器选择：

```text
.venv\Scripts\python.exe
```

macOS/Linux 下 IDE 的 Python 解释器选择：

```text
.venv/bin/python
```

## 构建可执行程序

Windows 使用 `python scripts/build.py`，macOS/Linux 使用 `python3 scripts/build.py`。

默认生成单文件，Windows 下为：

```text
dist\Qt Architecture Demo.exe
```

macOS 下为：

```text
dist/Qt Architecture Demo.app
```

Linux 下为：

```text
dist/Qt Architecture Demo
```

清理全部构建产物：

Windows 使用 `python scripts/clean.py`，macOS/Linux 使用 `python3 scripts/clean.py`。

上述命令不依赖 PowerShell 脚本，也不要求手工激活 `.venv`。

架构设计详见 [应用架构设计规范](docs/应用架构设计规范.md) 和 [从 Linux 式分层到应用功能模块化](docs/从Linux式分层到应用功能模块化.md)。
