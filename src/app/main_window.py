"""注册式多页面外壳，只负责导航、页面组织和异步退出。"""

from dataclasses import dataclass
import logging
from typing import Callable

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QSizeGrip
from PySide6.QtWidgets import QSizePolicy, QLayout, QSplitter, QListWidget, QListWidgetItem, QAbstractItemView, QApplication, QDialog, QMenuBar, QMessageBox, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from src.shared.ui_metrics import UI
from src.app.notifications import NotificationCenter
from src.shared.configuration import Configuration
from src.shared.tasks import TaskRunner

LOGGER = logging.getLogger("workbench.navigation")


@dataclass(frozen=True)
class PageDefinition:
    key: str
    title: str
    caption: str
    view: QWidget


class ApplicationWindow(QMainWindow):
    def __init__(self, pages: tuple[PageDefinition, ...], configuration: Configuration, tasks: TaskRunner, stop_producers: Callable[[], None]) -> None:
        super().__init__()
        self._tasks, self._stop_producers = tasks, stop_producers
        self._closing = False
        self._exit_ready = False
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        QApplication.instance().installEventFilter(self)
        self.setWindowTitle("Daylight · 桌面信息台")
        self.setMinimumSize(960, 680)
        values = configuration.get("app")
        self.resize(values["window_width"], values["window_height"])
        self.notifications = NotificationCenter(self)
        self._pages = QStackedWidget()
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setMinimumWidth(0)
        sidebar.setMaximumWidth(self.width() * 4 // 5)
        sidebar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._pages.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._expanded_width = self.width() // 5
        self._sidebar = sidebar
        self._collapsed = False
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(UI.sidebar_margin_x, UI.sidebar_margin_y, UI.sidebar_margin_x, UI.sidebar_margin_y)
        nav.setSpacing(UI.navigation_gap)
        nav.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        from src.app.sidebar import SidebarDelegate, SidebarList
        self._nav_list = SidebarList()
        self._settings_list = SidebarList()
        self._settings_list.setFixedHeight(UI.navigation_row_height * sum(page.key in ("logs", "settings") for page in pages))
        for listing in (self._nav_list, self._settings_list):
            listing.setObjectName("SidebarList")
            listing.setIconSize(QSize(UI.navigation_icon, UI.navigation_icon))
            listing.setMouseTracking(True)
            listing.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            listing.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            listing.setItemDelegate(SidebarDelegate(listing))
            listing.currentRowChanged.connect(lambda row, source=listing: self._select_navigation(source, row))
            listing.repeatedClicked.connect(self._toggle_sidebar)
        nav.addWidget(self._nav_list, 1)
        nav.addWidget(self._settings_list)
        initial = 0
        self._navigation_items = []
        for index, page in enumerate(pages):
            listing = self._settings_list if page.key in ("logs", "settings") else self._nav_list
            item = QListWidgetItem(page.title, listing)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setData(Qt.ItemDataRole.UserRole + 1, page.key)
            item.setSizeHint(QSize(0, UI.navigation_row_height))
            item.setToolTip(page.title)
            self._navigation_items.append(item)
            self._pages.addWidget(page.view)
            if page.key == values["initial_page"]:
                initial = index
        self._activity = QLabel("就绪")
        self._activity.setWordWrap(True)
        self._activity.setObjectName("Muted")
        self.statusBar().addWidget(self._activity, 1)
        self._page_definitions = pages
        self._build_menus()
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(UI.splitter_width)
        self._splitter.addWidget(sidebar)
        self._content_host = QWidget()
        self._content_host.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        content_layout = QVBoxLayout(self._content_host)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        content_layout.addWidget(self._pages)
        self._splitter.addWidget(self._content_host)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([self._expanded_width, self.width() - self._expanded_width - self._splitter.handleWidth()])
        self._splitter.splitterMoved.connect(self._sidebar_resized)
        self.setCentralWidget(self._splitter)
        self._pages.setCurrentIndex(initial)
        LOGGER.info("显示启动页面：%s", pages[initial].key)
        self._pages.currentChanged.connect(self._sync_navigation)
        self._pages.currentChanged.connect(lambda index: LOGGER.info("切换页面：%s", pages[index].key))
        self._sync_navigation(initial)
        tasks.activity_changed.connect(self._activity_changed)
        tasks.drained.connect(self._drained)

    def _select_navigation(self, listing, row):
        if row >= 0:
            self._pages.setCurrentIndex(listing.item(row).data(Qt.ItemDataRole.UserRole))

    def _sync_navigation(self, index):
        blockers = [QSignalBlocker(self._nav_list), QSignalBlocker(self._settings_list)]
        for listing in (self._nav_list, self._settings_list):
            listing.clearSelection()
            listing.setCurrentRow(-1)
        item = self._navigation_items[index]
        item.listWidget().setCurrentItem(item)

    def _set_sidebar_labels(self):
        for item, page in zip(self._navigation_items, self._page_definitions):
            item.setText("" if self._collapsed else page.title)
        self._sidebar_action.setChecked(not self._collapsed)

    def _collapse_sidebar(self):
        self._collapsed = True
        total = sum(self._splitter.sizes())
        self._splitter.setSizes([UI.sidebar_collapsed_width, max(0, total - UI.sidebar_collapsed_width)])
        self._set_sidebar_labels()
        self._check_sidebar_space()

    def _sidebar_resized(self, position, index):
        width, content = self._splitter.sizes()
        threshold = UI.sidebar_collapse_threshold
        if width < threshold:
            self._collapse_sidebar()
            return
        self._collapsed = False
        self._expanded_width = width
        self._set_sidebar_labels()
        self._check_sidebar_space()

    def _toggle_sidebar(self) -> None:
        if not self._collapsed:
            self._expanded_width = self._sidebar.width()
            self._collapse_sidebar()
            return
        self._collapsed = False
        total = sum(self._splitter.sizes())
        maximum = min(total, self.width() * 4 // 5)
        width = min(max(UI.sidebar_collapse_threshold, self._expanded_width), maximum)
        self._splitter.setSizes([width, total - width])
        self._set_sidebar_labels()
        self._check_sidebar_space()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_splitter"):
            self._sidebar.setMaximumWidth(self.width() * 4 // 5)
            QTimer.singleShot(0, self._check_sidebar_space)

    def _check_sidebar_space(self):
        # 只隐藏内容，保留右侧容器和分割手柄，拖回后可自动恢复。
        self._pages.setVisible(self._splitter.sizes()[1] >= self.width() / 2)

    def _build_menus(self) -> None:
        from src.app.title_bar import TitleBar
        header = TitleBar(self)
        self._menu_bar = header.menu
        self.setMenuWidget(header)
        bar = self._menu_bar
        file_menu = bar.addMenu("文件(&F)")
        close = file_menu.addAction("退出", self.close)
        close.setShortcut(QKeySequence.StandardKey.Quit)
        edit = bar.addMenu("编辑(&E)")
        self._edit_actions = []
        for title, method, shortcut in (("撤销", "undo", QKeySequence.StandardKey.Undo),
                                        ("重做", "redo", QKeySequence.StandardKey.Redo),
                                        ("剪切", "cut", QKeySequence.StandardKey.Cut),
                                        ("复制", "copy", QKeySequence.StandardKey.Copy),
                                        ("粘贴", "paste", QKeySequence.StandardKey.Paste),
                                        ("全选", "selectAll", QKeySequence.StandardKey.SelectAll)):
            action = edit.addAction(title, lambda checked=False, name=method: self._edit(name))
            # 快捷键由输入控件原有处理，避免与日志复制等局部快捷键冲突。
            action.setText(title + "\t" + QKeySequence(shortcut).toString(QKeySequence.SequenceFormat.NativeText))
            self._edit_actions.append((action, method))
        edit.aboutToShow.connect(self._update_edit_actions)
        view = bar.addMenu("视图(&V)")
        self._sidebar_action = view.addAction("展开侧边栏", self._toggle_sidebar)
        self._sidebar_action.setCheckable(True)
        self._sidebar_action.setChecked(True)
        self._sidebar_action.setShortcut("Ctrl+B")
        view.addSeparator()
        for index, page in enumerate(self._page_definitions):
            view.addAction(page.title, lambda checked=False, target=index: self._pages.setCurrentIndex(target))
        help_menu = bar.addMenu("帮助(&H)")
        help_menu.addAction("关于", self._about)
        self._menus = (file_menu, edit, view, help_menu)

    def _update_edit_actions(self) -> None:
        self._edit_target = QApplication.focusWidget()
        for action, method in self._edit_actions:
            target = self._edit_target
            enabled = target is not None and callable(getattr(target, method, None))
            if method in ("cut", "paste", "undo", "redo") and target is not None:
                enabled = enabled and not getattr(target, "isReadOnly", lambda: False)()
            action.setEnabled(enabled)

    def _edit(self, method) -> None:
        callback = getattr(getattr(self, "_edit_target", None), method, None)
        if callable(callback):
            callback()

    def _about(self) -> None:
        from version import APP_VERSION
        dialog = QDialog(self)
        dialog.setWindowTitle("关于 Daylight")
        dialog.setMinimumSize(UI.about_width, UI.about_height)
        dialog.resize(UI.about_width, UI.about_height)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(UI.about_margin, UI.about_margin, UI.about_margin, UI.about_margin)
        layout.setSpacing(16)
        from src.shared.brand_mark import BrandMark
        brand_row = QHBoxLayout()
        brand_row.setSpacing(18)
        brand_row.addWidget(BrandMark(dialog, UI.about_brand_size))
        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        brand = QLabel("日常信息台")
        brand.setObjectName("AboutBrand")
        caption = QLabel("DAYLIGHT")
        caption.setObjectName("AboutCaption")
        brand_text.addWidget(brand)
        brand_text.addWidget(caption)
        brand_row.addLayout(brand_text)
        layout.addLayout(brand_row)
        layout.addSpacing(4)
        version = QLabel(f"版本 {APP_VERSION}")
        version.setObjectName("Muted")
        layout.addWidget(version)
        description = QLabel("时钟、秒表、计时器、天气与日历。")
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addStretch()
        close = QPushButton("关闭")
        close.clicked.connect(dialog.close)
        close.setMinimumWidth(100)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dialog.open()

    def _activate_navigation(self, index) -> None:
        if index == self._pages.currentIndex():
            self._toggle_sidebar()
        else:
            self._pages.setCurrentIndex(index)

    def eventFilter(self, watched, event):
        # 状态栏角部手柄自行处理双轴缩放，不能被单边命中检测抢先消费。
        if isinstance(watched, QSizeGrip):
            return super().eventFilter(watched, event)
        # 无边框窗口仍使用平台提供的交互式缩放，不自行计算窗口拖动位置。
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget) and watched.window() is self:
            if event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
                point = self.mapFromGlobal(event.globalPosition().toPoint())
                edges = Qt.Edge(0)
                if point.x() < 5: edges |= Qt.Edge.LeftEdge
                elif point.x() >= self.width() - 5: edges |= Qt.Edge.RightEdge
                if point.y() < 5: edges |= Qt.Edge.TopEdge
                elif point.y() >= self.height() - 5: edges |= Qt.Edge.BottomEdge
                if edges and self.windowHandle() and self.windowHandle().startSystemResize(edges):
                    return True
        return super().eventFilter(watched, event)

    def _activity_changed(self, count: int) -> None:
        if self._closing:
            self._activity.setText(f"正在退出\n等待 {count} 个后台任务结束")
        else:
            self._activity.setText("就绪" if count == 0 else f"后台任务 {count} 个")

    def _drained(self) -> None:
        if self._closing:
            self._exit_ready = True
            LOGGER.info("全部后台任务已结束，关闭窗口")
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event) -> None:
        if self._exit_ready:
            event.accept()
            return
        if not self._closing:
            LOGGER.info("用户关闭主窗口，开始停止各模块")
            self._closing = True
            self.notifications.close()
            self._stop_producers()
            self.centralWidget().setEnabled(False)
            self._menu_bar.setEnabled(False)
            self._activity_changed(self._tasks.active_count)
            if self._tasks.shutdown():
                self._exit_ready = True
                event.accept()
                return
        event.ignore()
