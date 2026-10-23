# Python Graphical Application Framework

基于 Python / PySide6 的跨平台多页面桌面应用框架。内置 **Daylight 桌面信息台**：时钟、天气、日志和注册式设置。通过真实但独立的通用功能，演示单向数据流、后台任务生命周期、模块配置与资源管理；不再使用计数器示例。

## 功能

| 页面 | 能力 |
| --- | --- |
| 时钟 | SNTP 联网校准、定期同步、手动同步与取消；可设置服务器、端口、间隔、UTC/本地时区。只校准应用显示，不修改系统时钟。 |
| 天气 | 搜索并选择地点、当前天气、未来 24 小时逐小时明细、10–16 天预报、最近 0–7 天历史模型数据；支持来源注册及兼容接口地址配置。 |
| 日志 | 标准库日志统一记录，终端和每次启动独立文件；等级筛选、自动跟随、批次增量显示。清空视图不会删除日志文件。 |
| 设置 | 各模块注册字段自动生成表单；独立 JSON 持久化；本地文件分类查看、打开目录、清理旧日志和缓存。 |

天气默认使用 [Open-Meteo](https://open-meteo.com/en/docs)。该来源最多支持 16 天预报，不伪造第 17–20 天；过去几天是历史模型数据，不是实测气象站记录。免费服务有使用限制，商业部署前应核对服务条款并接入合适来源。设置接口地址只适用于相同协议，其他服务需新增适配器。联网失败会显示原因，不阻塞界面；天气保留同一地点上次成功结果。

## 开发与运行

安装支持当前依赖的 Python，Windows 使用 `python`，Linux/macOS 使用 `python3`：

```bash
python3 main.py
```

入口自动准备 `.venv` 和依赖。IDE 解释器选择 `.venv/bin/python`（Windows 为 `.venv\Scripts\python.exe`）。开发环境依赖见 `requirements.txt`；网络、日志、配置使用标准库，没有额外网络 SDK。时钟需要网络允许 UDP NTP；天气需要访问配置的 HTTP(S) 服务。

## 配置和用户文件

只读默认值在 `assets/defaults/`，按模块分别保存：`app.json`、`appearance.json`、`clock.json`、`weather.json`、`location.json`、`logging.json`。每个文件统一包含 `schema_version` 和 `values`。

**设置 → 外观** 可选择 Daylight 浅色、Nightfall 深色或跟随系统，保存后立即生效并保留到下次启动。系统未报告色彩偏好时使用浅色。主题统一覆盖页面、下拉菜单、表格和日志；系统标题栏由桌面环境控制。

首次启动将默认值写入用户配置；以后只使用用户文件，升级时补齐缺失字段，保留已有值。保存采用同目录临时文件与原子替换，成功后才通知模块。无效或来自更高版本的配置不会被静默覆盖，会明确提示。

每次启动逐个检查已注册模块：缺少整个文件时按软件自带默认 JSON 创建；文件存在时，即使版本相同也递归补齐缺项，不覆盖已有有效值。版本号用于识别模块迁移和阻止旧软件加载更高版本配置，不代表自动理解任意字段重命名或类型变化；这类变化需模块提供迁移规则。当前时钟配置版本为 2，其余模块为 1。

各分类的“恢复当前分类默认配置”经确认后，直接用软件自带默认值覆盖该分类用户 JSON（含该分类额外扩展字段），同步表单并通知功能，无需再次保存。其他分类、日志和数据不受影响。窗口尺寸、启动页面仍在下次启动时生效。恢复操作没有自动撤销；需要保留旧值时请先通过“打开配置位置”备份该文件。

各设置分类提供“打开配置位置”，打开对应 JSON 所在文件夹，并显示可复制的完整路径。手动修改配置文件后需要重启应用；通过设置表单保存则按模块规则生效。

时钟默认使用阿里云 `ntp.aliyun.com:123`（[官方说明](https://help.aliyun.com/zh/eci/user-guide/configure-the-ntp-service)），仍可在设置中修改。时钟配置升级至版本 2 时，将旧默认 `pool.ntp.org:123` 一次性替换为新地址，不改其他自定义地址或端口。实际连通性取决于所在网络是否允许 UDP 123。

用户目录由 Qt `QStandardPaths` 决定，不写入安装目录或仓库。以下是常见位置，环境变量或系统策略可能改变实际路径，以 **设置 → 本地文件** 为准：

| 类型 | Linux | Windows | macOS |
| --- | --- | --- | --- |
| 配置 | `~/.config/GraphicalWorkbench/modules/` | `%LOCALAPPDATA%/GraphicalWorkbench/modules/` | `~/Library/Preferences/GraphicalWorkbench/modules/` |
| 数据 | `~/.local/share/GraphicalWorkbench/data/` | `%LOCALAPPDATA%/GraphicalWorkbench/data/` | `~/Library/Application Support/GraphicalWorkbench/data/` |
| 缓存 | `~/.cache/GraphicalWorkbench/` | `%LOCALAPPDATA%/GraphicalWorkbench/cache/` | `~/Library/Caches/GraphicalWorkbench/` |
| 日志 | `~/.local/state/GraphicalWorkbench/logs/` | `%LOCALAPPDATA%/GraphicalWorkbench/State/logs/` | `~/Library/Preferences/GraphicalWorkbench/State/logs/` |

日志命名为 `session-时间戳.log`，可设置保留文件数。本地文件管理不提供删除配置或数据的按钮；清理旧日志会保留当前会话。卸载可执行程序通常不会自动删除这些用户文件。

日志在运行期间实时写入文件，不是等退出时才保存。日志页默认展示“本次运行 · 实时日志”，可从会话列表选择之前的日志，点击“刷新列表”重新扫描，点击“打开日志位置”查看完整文件。历史预览在后台读取，最多读取文件末尾 2 MiB，并按设置的行数上限展示；截断时会提示。查看历史不影响当前日志继续记录，切回实时日志即可查看新事件。支持历史等级筛选和异常堆栈显示。

“清空视图”不影响文件；“清除全部日志”需确认，删除本应用 `session-*.log` 历史文件，并锁住当前写入句柄清空当前文件内容，之后立即继续记录，因此清理后当前文件会重新出现新记录。不会删除配置或其他文件，清理不可撤销，失败文件会明确提示。默认保留最近 20 个会话文件，启动或应用日志设置时清理超出数量的旧文件。

## 代码组织

### 当前位置和详细日志

**设置 → 当前位置**：默认启用网络 IP 定位，启动时和定位设置变更后请求一次。可分别关闭对时钟或天气的应用，并配置兼容服务地址、超时。默认使用 [ipwho.is](https://ipwhois.io/documentation)，服务会获知设备公网出口 IP；仅提供大致位置，VPN/代理可能使位置不准确，当前未接入 GPS。接口实际可用性取决于网络，应用不保证国内网络一定可访问。

定位成功后天气坐标保存到 `weather.json`；时钟使用返回的时区并标记“IP 定位”，按当前日期计算时区偏移，显式选择 UTC 时仍显示 UTC。关闭定位或定位失败时，天气保留已保存地点（首次为上海），时钟使用系统时区。定位期间手动修改天气地点不会被随后返回的结果覆盖；如需跨启动一直使用手动地点，请关闭“天气使用当前位置”。不会改变操作系统时间或时区。

日志覆盖启动退出、页面导航、配置加载/创建/迁移/补齐/保存/恢复/应用、HTTP 与 NTP、定位、天气、任务成功失败及取消、文件管理、主题、通知和日志查看操作。INFO 记录主要过程，DEBUG 记录细节与过期结果丢弃；设置 → 日志可调整等级。每条文件日志包含等级、时间、线程、模块、消息，任务附带代次与耗时。不会对每秒走时、重绘或日志刷新逐次写日志。常规事件不记录整份配置、定位响应、经纬度或查询内容；异常堆栈可能包含运行环境路径等诊断信息，分享日志前仍需检查。

```text
assets/defaults/           模块默认 JSON（随程序打包）
src/app/                   显式装配、页面注册、外壳、主题、通知
src/features/
  clock/                   时间采样、状态、页面与设置定义
  weather/                 来源协议、适配器、状态、页面与设置定义
  location/                网络 IP 定位、结果验证与生命周期
  logs/                    日志批量展示
  settings/                注册式表单与本地文件管理
src/shared/                配置、路径、任务、HTTP、日志及基础控件
tests/                     离线测试样例
scripts/                   构建与清理
docs/                      架构与视觉规范
```

后台工作对象运行在独立线程，使用取消标志和请求代次；界面只接收结果。关闭窗口先停止生产新任务，再异步等待线程结束。隐藏页面停止昂贵重绘，日志事件按批次提交。异步错误合并到一个非模态通知窗口。

新增页面：建立功能目录，在 `app/bootstrap.py` 装配依赖并注册 `PageDefinition`。新增设置：定义 `SettingsSection`、加入默认 JSON 并注册，表单和持久化由基础设施承担。新增天气来源：实现 `WeatherProvider` 并注册，不让界面解析服务响应。

## 构建与测试

```bash
python3 scripts/build.py
python3 scripts/clean.py
```

在目标系统本机构建：Windows 输出 `dist/Graphical Workbench.exe`，Linux 输出 `dist/Graphical Workbench`，macOS 输出 `dist/Graphical Workbench.app`。构建会包含默认配置资源；用户可修改配置仍在用户目录。签名、公证和安装器不在当前脚本范围。

安装依赖后可执行离线测试，不连接外部服务、不使用真实用户配置：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Windows 对应使用 `.venv\Scripts\python.exe -m unittest discover -s tests -v`。

## 设计文档

- [应用架构设计规范](docs/应用架构设计规范.md)
- [多页面应用落地设计](docs/多页面应用落地设计.md)
- [界面设计规范](docs/界面设计规范.md)
- [从 Linux 式分层到应用功能模块化](docs/从Linux式分层到应用功能模块化.md)
