"""注册式多页面外壳，只负责导航、页面组织和异步退出。"""

from dataclasses import dataclass
import logging
from typing import Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

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
        self.setWindowTitle("Daylight · 桌面信息台")
        self.setMinimumSize(960, 680)
        values = configuration.get("app")
        self.resize(values["window_width"], values["window_height"])
        self.notifications = NotificationCenter(self)
        self._pages = QStackedWidget()
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(208)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(16, 22, 16, 18)
        nav.setSpacing(8)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        mark = QLabel()
        mark.setObjectName("BrandMark")
        mark.setProperty("themeIcon", "sunrise")
        mark.setFixedSize(40, 40)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setAccessibleName("Daylight 日出标志")
        brand_row.addWidget(mark)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        brand = QLabel("日常信息台")
        brand.setObjectName("Brand")
        note = QLabel("DAYLIGHT")
        note.setObjectName("BrandCaption")
        brand_text.addWidget(brand)
        brand_text.addWidget(note)
        brand_row.addLayout(brand_text)
        brand_row.addStretch()
        nav.addLayout(brand_row)
        nav.addSpacing(12)
        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        nav.addWidget(divider)
        nav.addSpacing(12)
        group = QButtonGroup(self)
        group.setExclusive(True)
        initial = 0
        buttons = []
        for index, page in enumerate(pages):
            button = QPushButton(page.title)
            button.setProperty("navigationIcon", page.key)
            button.setIconSize(QSize(20, 20))
            button.setObjectName("Navigation")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, target=index: self._pages.setCurrentIndex(target))
            group.addButton(button)
            nav.addWidget(button)
            buttons.append(button)
            self._pages.addWidget(page.view)
            if page.key == values["initial_page"]:
                initial = index
        nav.addStretch()
        self._activity = QLabel("就绪")
        self._activity.setWordWrap(True)
        self._activity.setObjectName("Muted")
        nav.addWidget(self._activity)
        surface = QWidget()
        row = QHBoxLayout(surface)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(sidebar)
        row.addWidget(self._pages, 1)
        self.setCentralWidget(surface)
        self._pages.setCurrentIndex(initial)
        LOGGER.info("显示启动页面：%s", pages[initial].key)
        self._pages.currentChanged.connect(lambda index: LOGGER.info("切换页面：%s", pages[index].key))
        buttons[initial].setChecked(True)
        tasks.activity_changed.connect(self._activity_changed)
        tasks.drained.connect(self._drained)

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
            self._activity_changed(self._tasks.active_count)
            if self._tasks.shutdown():
                self._exit_ready = True
                event.accept()
                return
        event.ignore()
