import logging
import time

from utils.config_loader import save_config

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QSpinBox, QLabel, QMessageBox,
    QListWidget, QListWidgetItem, QCompleter, QSplitter, QFrame,
    QSizePolicy, QProgressBar, QApplication,
)
from PySide6.QtCore import Signal, Qt, QStringListModel, QTimer
from PySide6.QtGui import QColor, QFont

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  CollapsibleGroupBox: 可折叠的 GroupBox
# ------------------------------------------------------------------ #
class CollapsibleGroupBox(QGroupBox):
    """点击标题可折叠/展开内容的 GroupBox。"""

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self._collapsed = False
        self._content_widget: QWidget | None = None
        self._title_base = title
        self.setCheckable(True)
        self.setChecked(True)
        self.toggled.connect(self._on_toggled)

    def set_content_widget(self, widget: QWidget):
        self._content_widget = widget

    def _on_toggled(self, checked: bool):
        self._collapsed = not checked
        if self._content_widget:
            self._content_widget.setVisible(checked)

    def set_summary(self, summary: str):
        """折叠时在标题后显示摘要信息。延迟执行避免布局期间触发重绘。"""
        if summary:
            new_title = f"{self._title_base}  [{summary}]"
        else:
            new_title = self._title_base
        QTimer.singleShot(0, lambda t=new_title: self.setTitle(t))


class DetectionTab(QWidget):
    """落地检测标签页：发送配置 + 检测结果 + 状态栏。

    布局：左侧边栏（配置+列表）| 右侧主区域（操作栏+筛选栏+进度条+结果表格）
    通过 QSplitter 分割，表格占据最大空间。

    扁平化表格列：序号 | 线路名 | 运营商 | 号段 | 发送状态 | 送达状态 | 落地状态 | 耗时 | 失败原因
    每行 = 一个 (线路, 运营商) 组合，行数 = 线路数 x 运营商数。
    """

    start_requested = Signal(dict)
    stop_requested = Signal()
    retest_requested = Signal()
    recheck_requested = Signal()
    load_operators_requested = Signal(dict)
    refresh_countries_requested = Signal()

    # 扁平化表格列定义
    COL_SEQ = 0       # 序号
    COL_SERVER = 1    # 线路名
    COL_OPERATOR = 2  # 运营商
    COL_PHONE = 3     # 号段
    COL_SEND = 4      # 发送状态
    COL_DELIVER = 5   # 送达状态
    COL_LANDED = 6    # 落地状态
    COL_ELAPSED = 7   # 耗时
    COL_REASON = 8    # 失败原因
    TOTAL_COLS = 9
    HEADERS = ["序号", "线路名", "运营商", "号段", "发送状态", "送达状态", "落地状态", "耗时", "失败原因"]

    # 服务器行分组背景色（交替）
    _SERVER_COLORS = ["#FFFFFF", "#F8FAFC"]

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._num_servers = 0
        self._num_operators = 0
        self._current_operators: list[str] = []
        self._current_filter = "all"  # all / landed / not_landed / testing / failed
        self._current_operator_filter: str | None = None  # None = 不筛选运营商
        self._operator_filter_buttons: dict[str, QPushButton] = {}
        self._updating = False  # 防止递归重绘的守卫标志
        self._init_ui()

    # ------------------------------------------------------------------ #
    #  _build_sidebar: 左侧边栏 — 国家选择 / 服务器列表 / 运营商列表
    # ------------------------------------------------------------------ #
    # 可折叠面板样式（共用）
    _SECTION_STYLE = """
        QGroupBox {
            background-color: #FAFBFC;
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            margin-top: 12px;
            padding-top: 18px;
            font-weight: 600;
            font-size: 12px;
        }
        QGroupBox::title {
            color: #2563EB;
            background-color: #FAFBFC;
            padding: 2px 8px;
            border-radius: 4px;
        }
    """

    # 侧边栏小按钮样式
    _SMALL_BTN = "QPushButton { font-size: 12px; padding: 2px 8px; border-radius: 5px; }"

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setMinimumWidth(260)
        sidebar.setMaximumWidth(400)
        sidebar.setStyleSheet("""
            QWidget#sidebar_root {
                background-color: #FFFFFF;
                border-right: 1px solid #F1F5F9;
                border-radius: 10px;
            }
        """)
        sidebar.setObjectName("sidebar_root")
        vbox = QVBoxLayout(sidebar)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(6)

        # -- 第一行：国家选择 --
        country_row = QHBoxLayout()
        country_row.setSpacing(6)
        country_lbl = QLabel("国家")
        country_lbl.setStyleSheet("color: #64748B; font-size: 12px; font-weight: 500;")
        country_lbl.setFixedWidth(30)
        country_row.addWidget(country_lbl)
        self.country_combo = QComboBox()
        self.country_combo.setEditable(True)
        self.country_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.country_combo.addItem("-- 选择国家 --")
        self.country_combo.setFixedHeight(28)
        self._country_completer = QCompleter()
        self._country_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._country_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.country_combo.setCompleter(self._country_completer)
        self._country_completer.activated[str].connect(self._on_completer_activated)
        self.country_combo.currentIndexChanged.connect(self._on_country_changed)
        country_row.addWidget(self.country_combo, stretch=1)
        vbox.addLayout(country_row)

        # -- 第二行：刷新 + 超时 --
        opt_row = QHBoxLayout()
        opt_row.setSpacing(6)
        self.refresh_countries_btn = QPushButton("刷新国家")
        self.refresh_countries_btn.setFixedHeight(28)
        self.refresh_countries_btn.setStyleSheet(self._SMALL_BTN)
        self.refresh_countries_btn.clicked.connect(self._on_refresh_countries)
        opt_row.addWidget(self.refresh_countries_btn)
        opt_row.addStretch()
        timeout_lbl = QLabel("超时")
        timeout_lbl.setStyleSheet("color: #64748B; font-size: 12px;")
        opt_row.addWidget(timeout_lbl)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 3600)
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.setFixedSize(80, 28)
        self.timeout_spin.setToolTip("检测超时时间（秒）")
        settings = self.config.get("settings", {})
        self.timeout_spin.setValue(settings.get("timeout", 120))
        opt_row.addWidget(self.timeout_spin)
        vbox.addLayout(opt_row)

        # 兼容 set_summary 的 stub
        self.country_group = type('_Stub', (), {
            'set_summary': lambda self, s: None,
        })()

        # -- EIMS 线路（可折叠） --
        self.server_group = CollapsibleGroupBox("EIMS 线路")
        self.server_group.setStyleSheet(self._SECTION_STYLE)
        sg_content = QWidget()
        sg_layout = QVBoxLayout(sg_content)
        sg_layout.setContentsMargins(8, 4, 8, 6)
        sg_layout.setSpacing(4)

        srv_top_row = QHBoxLayout()
        srv_top_row.setSpacing(6)
        self.server_summary_label = QLabel("已选 0/0")
        self.server_summary_label.setStyleSheet("color: #64748B; font-size: 11px; font-weight: normal;")
        srv_top_row.addWidget(self.server_summary_label)
        srv_top_row.addStretch()
        self.select_all_servers_btn = QPushButton("全选")
        self.select_all_servers_btn.setFixedHeight(28)
        self.select_all_servers_btn.setStyleSheet(self._SMALL_BTN)
        self.select_all_servers_btn.clicked.connect(self._on_select_all_servers)
        self.deselect_all_servers_btn = QPushButton("取消")
        self.deselect_all_servers_btn.setFixedHeight(28)
        self.deselect_all_servers_btn.setStyleSheet(self._SMALL_BTN)
        self.deselect_all_servers_btn.clicked.connect(self._on_deselect_all_servers)
        srv_top_row.addWidget(self.select_all_servers_btn)
        srv_top_row.addWidget(self.deselect_all_servers_btn)
        sg_layout.addLayout(srv_top_row)

        self.server_list = QListWidget()
        self.server_list.setAlternatingRowColors(True)
        self.server_list.setStyleSheet("QListWidget::item { padding: 3px 8px; }")
        self.server_list.itemChanged.connect(self._update_server_summary)
        sg_layout.addWidget(self.server_list, stretch=1)

        sg_outer = QVBoxLayout(self.server_group)
        sg_outer.setContentsMargins(0, 16, 0, 0)
        sg_outer.addWidget(sg_content)
        self.server_group.set_content_widget(sg_content)
        vbox.addWidget(self.server_group, stretch=1)

        # -- 运营商（可折叠） --
        self.op_group = CollapsibleGroupBox("运营商")
        self.op_group.setStyleSheet(self._SECTION_STYLE)
        og_content = QWidget()
        og_layout = QVBoxLayout(og_content)
        og_layout.setContentsMargins(8, 4, 8, 6)
        og_layout.setSpacing(4)

        op_top_row = QHBoxLayout()
        op_top_row.setSpacing(6)
        self.load_operators_btn = QPushButton("加载")
        self.load_operators_btn.setProperty("class", "primary")
        self.load_operators_btn.setFixedHeight(28)
        self.load_operators_btn.setToolTip("从 HeroSMS 获取当前国家的运营商")
        self.load_operators_btn.clicked.connect(self._on_load_operators)
        op_top_row.addWidget(self.load_operators_btn)
        self.operator_input = QLineEdit()
        self.operator_input.setPlaceholderText("手动输入运营商...")
        self.operator_input.setFixedHeight(28)
        op_top_row.addWidget(self.operator_input, stretch=1)
        self.add_operator_btn = QPushButton("+")
        self.add_operator_btn.setFixedSize(28, 28)
        self.add_operator_btn.setToolTip("添加手动输入的运营商")
        self.add_operator_btn.setStyleSheet("QPushButton { font-size: 15px; font-weight: bold; border-radius: 6px; padding: 0; }")
        self.add_operator_btn.clicked.connect(self._on_add_operator)
        op_top_row.addWidget(self.add_operator_btn)
        og_layout.addLayout(op_top_row)

        op_btn_row = QHBoxLayout()
        op_btn_row.setSpacing(6)
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.setFixedHeight(28)
        self.select_all_btn.setStyleSheet(self._SMALL_BTN)
        self.select_all_btn.clicked.connect(self._on_select_all_operators)
        self.deselect_all_btn = QPushButton("取消")
        self.deselect_all_btn.setFixedHeight(28)
        self.deselect_all_btn.setStyleSheet(self._SMALL_BTN)
        self.deselect_all_btn.clicked.connect(self._on_deselect_all_operators)
        self.remove_operator_btn = QPushButton("删除选中")
        self.remove_operator_btn.setProperty("class", "danger")
        self.remove_operator_btn.setFixedHeight(28)
        self.remove_operator_btn.clicked.connect(self._on_remove_checked_operators)
        op_btn_row.addWidget(self.select_all_btn)
        op_btn_row.addWidget(self.deselect_all_btn)
        op_btn_row.addWidget(self.remove_operator_btn)
        op_btn_row.addStretch()
        og_layout.addLayout(op_btn_row)

        self.operator_list = QListWidget()
        self.operator_list.setAlternatingRowColors(True)
        self.operator_list.setStyleSheet("QListWidget::item { padding: 3px 8px; }")
        og_layout.addWidget(self.operator_list, stretch=1)

        og_outer = QVBoxLayout(self.op_group)
        og_outer.setContentsMargins(0, 16, 0, 0)
        og_outer.addWidget(og_content)
        self.op_group.set_content_widget(og_content)
        vbox.addWidget(self.op_group, stretch=1)

        # -- 活跃号码（可折叠，默认折叠） --
        self.cache_group = CollapsibleGroupBox("活跃号码")
        self.cache_group.setStyleSheet(self._SECTION_STYLE)
        cache_content = QWidget()
        cg2_layout = QVBoxLayout(cache_content)
        cg2_layout.setContentsMargins(8, 4, 8, 6)
        cg2_layout.setSpacing(4)

        cache_top_row = QHBoxLayout()
        cache_top_row.setSpacing(6)
        self.cache_summary_label = QLabel("无缓存号码")
        self.cache_summary_label.setStyleSheet("color: #64748B; font-size: 11px; font-weight: normal;")
        cache_top_row.addWidget(self.cache_summary_label)
        cache_top_row.addStretch()
        self.clear_cache_btn = QPushButton("清空缓存")
        self.clear_cache_btn.setProperty("class", "danger")
        self.clear_cache_btn.setFixedHeight(28)
        cache_top_row.addWidget(self.clear_cache_btn)
        cg2_layout.addLayout(cache_top_row)

        self.cache_list = QListWidget()
        self.cache_list.setAlternatingRowColors(True)
        self.cache_list.setStyleSheet("QListWidget { font-size: 11px; } QListWidget::item { padding: 2px 6px; }")
        self.cache_list.setMaximumHeight(80)
        cg2_layout.addWidget(self.cache_list)

        cg2_outer = QVBoxLayout(self.cache_group)
        cg2_outer.setContentsMargins(0, 16, 0, 0)
        cg2_outer.addWidget(cache_content)
        self.cache_group.set_content_widget(cache_content)
        self.cache_group.setChecked(False)
        vbox.addWidget(self.cache_group)

        return sidebar

    # ------------------------------------------------------------------ #
    #  _build_main_area: 右侧主区域 — 操作栏 + 筛选栏 + 进度条 + 结果表格
    # ------------------------------------------------------------------ #
    def _build_main_area(self) -> QWidget:
        main = QWidget()
        main.setStyleSheet("QWidget#main_area { background-color: #F8FAFC; border-radius: 8px; }")
        main.setObjectName("main_area")
        vbox = QVBoxLayout(main)
        vbox.setContentsMargins(6, 6, 6, 6)
        vbox.setSpacing(4)

        # -- 顶部栏：操作按钮 + 进度状态（单行） --
        top_card = QFrame()
        top_card.setObjectName("top_card")
        top_card.setStyleSheet("""
            QFrame#top_card {
                background-color: #FFFFFF;
                border: 1px solid #F1F5F9;
                border-radius: 8px;
            }
        """)
        top_inner = QHBoxLayout(top_card)
        top_inner.setContentsMargins(8, 6, 8, 6)
        top_inner.setSpacing(6)

        self.start_btn = QPushButton("开始检测")
        self.start_btn.setProperty("class", "primary")
        self.start_btn.setFixedHeight(30)
        self.start_btn.setMinimumWidth(90)
        self.start_btn.setStyleSheet("QPushButton { font-size: 12px; font-weight: bold; border-radius: 6px; }")
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setProperty("class", "danger")
        self.stop_btn.setFixedHeight(30)
        self.stop_btn.setMinimumWidth(60)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("QPushButton { border-radius: 6px; font-size: 12px; }")
        self.retest_btn = QPushButton("重新测试")
        self.retest_btn.setFixedHeight(30)
        self.retest_btn.setMinimumWidth(88)
        self.retest_btn.setEnabled(False)
        self.retest_btn.setToolTip("复用当前号码，只重新测试未落地的服务器")
        self.retest_btn.setStyleSheet("QPushButton { border-radius: 6px; font-size: 12px; }")
        self.recheck_btn = QPushButton("落地查询")
        self.recheck_btn.setFixedHeight(30)
        self.recheck_btn.setMinimumWidth(88)
        self.recheck_btn.setEnabled(False)
        self.recheck_btn.setToolTip("使用上一轮 UUID 重新查询 HeroSMS 收信状态")
        self.recheck_btn.setStyleSheet("QPushButton { border-radius: 6px; font-size: 12px; }")
        top_inner.addWidget(self.start_btn)
        top_inner.addWidget(self.stop_btn)
        top_inner.addWidget(self.retest_btn)
        top_inner.addWidget(self.recheck_btn)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet("color: #E2E8F0;")
        sep1.setFixedHeight(22)
        top_inner.addWidget(sep1)

        self.progress_label = QLabel("就绪")
        self.progress_label.setStyleSheet("font-weight: bold; color: #2563EB; font-size: 12px;")
        top_inner.addWidget(self.progress_label)

        top_inner.addStretch()

        # 进度条嵌入顶部栏右侧
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setFixedWidth(140)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v/%m")
        top_inner.addWidget(self.progress_bar)

        vbox.addWidget(top_card)

        # -- 统计 + 筛选（两行卡片） --
        filter_card = QFrame()
        filter_card.setObjectName("filter_card")
        filter_card.setStyleSheet("""
            QFrame#filter_card {
                background-color: #FFFFFF;
                border: 1px solid #F1F5F9;
                border-radius: 8px;
            }
        """)
        filter_vbox = QVBoxLayout(filter_card)
        filter_vbox.setContentsMargins(8, 6, 8, 6)
        filter_vbox.setSpacing(4)

        # 第一行：统计徽章 + 状态标签
        stats_row = QHBoxLayout()
        stats_row.setSpacing(6)
        self.landed_label = self._make_stat_badge("已落地", "0", "#10B981", "#ECFDF5")
        self.not_landed_label = self._make_stat_badge("未落地", "0", "#EF4444", "#FEF2F2")
        self.testing_label = self._make_stat_badge("检测中", "0", "#F59E0B", "#FFFBEB")
        self.failed_label = self._make_stat_badge("失败", "0", "#94A3B8", "#F1F5F9")
        stats_row.addWidget(self.landed_label)
        stats_row.addWidget(self.not_landed_label)
        stats_row.addWidget(self.testing_label)
        stats_row.addWidget(self.failed_label)
        stats_row.addStretch()
        self.status_label = QLabel("")
        stats_row.addWidget(self.status_label)
        filter_vbox.addLayout(stats_row)

        # 分隔线
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #F1F5F9;")
        sep2.setFixedHeight(1)
        filter_vbox.addWidget(sep2)

        # 第二行：状态筛选按钮 + 运营商筛选按钮
        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)
        _FILTER_BTN = "QPushButton { font-size: 11px; padding: 2px 10px; border-radius: 10px; }"
        self._filter_buttons: dict[str, QPushButton] = {}
        filter_defs = [
            ("all", "全部"),
            ("landed", "已落地"),
            ("not_landed", "未落地"),
            ("testing", "检测中"),
            ("failed", "失败"),
        ]
        for key, text in filter_defs:
            btn = QPushButton(text)
            btn.setFixedHeight(24)
            btn.setCheckable(True)
            btn.setProperty("filter_key", key)
            btn.setStyleSheet(_FILTER_BTN)
            btn.clicked.connect(lambda checked, k=key: self._on_filter_clicked(k))
            filter_row.addWidget(btn)
            self._filter_buttons[key] = btn
        self._filter_buttons["all"].setChecked(True)

        # 运营商筛选区域
        self._operator_sep = QFrame()
        self._operator_sep.setFrameShape(QFrame.Shape.VLine)
        self._operator_sep.setStyleSheet("color: #E2E8F0;")
        self._operator_sep.setFixedHeight(18)
        self._operator_sep.setVisible(False)
        filter_row.addWidget(self._operator_sep)

        self._operator_filter_layout = QHBoxLayout()
        self._operator_filter_layout.setSpacing(4)
        filter_row.addLayout(self._operator_filter_layout)

        filter_row.addStretch()
        filter_vbox.addLayout(filter_row)

        vbox.addWidget(filter_card)

        # -- 结果表格 --
        self.result_table = QTableWidget(0, self.TOTAL_COLS)
        self.result_table.setAlternatingRowColors(False)
        self.result_table.setHorizontalHeaderLabels(self.HEADERS)
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setWordWrap(False)
        self.result_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #F1F5F9;
                border-radius: 6px;
                font-size: 12px;
            }
        """)

        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_SEQ, QHeaderView.ResizeMode.Fixed)
        self.result_table.setColumnWidth(self.COL_SEQ, 46)
        self.result_table.setColumnWidth(self.COL_SERVER, 120)
        self.result_table.setColumnWidth(self.COL_OPERATOR, 90)
        self.result_table.setColumnWidth(self.COL_PHONE, 120)
        self.result_table.setColumnWidth(self.COL_SEND, 90)
        self.result_table.setColumnWidth(self.COL_DELIVER, 90)
        self.result_table.setColumnWidth(self.COL_LANDED, 100)
        self.result_table.setColumnWidth(self.COL_ELAPSED, 60)
        header.setSectionResizeMode(self.COL_REASON, QHeaderView.ResizeMode.Stretch)

        vbox.addWidget(self.result_table, stretch=1)

        return main

    # ------------------------------------------------------------------ #
    #  辅助：创建统计徽章标签
    # ------------------------------------------------------------------ #
    def _make_stat_badge(self, label: str, value: str, color: str, bg: str) -> QLabel:
        widget = QLabel(f"{label}:{value}")
        widget.setStyleSheet(f"""
            background-color: {bg};
            color: {color};
            font-weight: bold;
            font-size: 11px;
            padding: 2px 12px;
            border-radius: 10px;
            border: 1px solid {color}30;
        """)
        widget.setProperty("stat_color", color)
        widget.setProperty("stat_bg", bg)
        widget.setProperty("stat_label", label)
        return widget

    def _update_stat_badge(self, widget: QLabel, value: int):
        label = widget.property("stat_label")
        widget.setText(f"{label}:{value}")

    # ------------------------------------------------------------------ #
    #  _init_ui: 组装整体布局
    # ------------------------------------------------------------------ #
    def _init_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        splitter.setChildrenCollapsible(False)

        sidebar = self._build_sidebar()
        main_area = self._build_main_area()

        splitter.addWidget(sidebar)
        splitter.addWidget(main_area)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([270, 730])

        root.addWidget(splitter)

        # 信号连接
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        self.retest_btn.clicked.connect(self._on_retest)
        self.recheck_btn.clicked.connect(self._on_recheck)

        self._success_count = 0
        self._fail_count = 0

        # 时间戳节流：最多每 0.5 秒刷新一次统计和筛选
        self._last_refresh_time = 0.0

    # ---------- 筛选栏 ----------

    def _on_filter_clicked(self, key: str):
        """筛选按钮点击：高亮当前按钮，隐藏/显示表格行。"""
        self._current_filter = key
        for k, btn in self._filter_buttons.items():
            btn.setChecked(k == key)
        self._apply_filter()

    def _on_operator_filter_clicked(self, operator: str):
        """运营商筛选按钮点击：切换选中状态。"""
        if self._current_operator_filter == operator:
            # 再次点击取消选中
            self._current_operator_filter = None
        else:
            self._current_operator_filter = operator
        for name, btn in self._operator_filter_buttons.items():
            btn.setChecked(name == self._current_operator_filter)
        self._apply_filter()

    def _apply_filter(self):
        """根据当前筛选条件（状态 + 运营商）显示/隐藏表格行。"""
        self.result_table.setUpdatesEnabled(False)
        try:
            for row in range(self.result_table.rowCount()):
                # 状态筛选
                landed_item = self.result_table.item(row, self.COL_LANDED)
                status_visible = True
                if landed_item:
                    text = landed_item.text()
                    if self._current_filter == "landed":
                        status_visible = "已落地" in text
                    elif self._current_filter == "not_landed":
                        status_visible = "未落地" in text
                    elif self._current_filter == "testing":
                        status_visible = "检测中" in text or "查询中" in text or "重测中" in text
                    elif self._current_filter == "failed":
                        status_visible = "失败" in text or "已停止" in text or "取号失败" in text

                # 运营商筛选
                op_visible = True
                if self._current_operator_filter is not None:
                    op_item = self.result_table.item(row, self.COL_OPERATOR)
                    if op_item:
                        op_visible = op_item.text().upper() == self._current_operator_filter.upper()
                    else:
                        op_visible = False

                self.result_table.setRowHidden(row, not (status_visible and op_visible))
        finally:
            self.result_table.setUpdatesEnabled(True)
            self.result_table.viewport().repaint()

    def _setup_operator_filter_buttons(self, operators: list[str]):
        """根据运营商列表动态创建筛选按钮。"""
        self._clear_operator_filter_buttons()
        if not operators:
            return

        # 过滤掉 "any"，只为具名运营商创建按钮
        named_ops = [op for op in operators if op and op != "any"]
        if not named_ops:
            return

        self._operator_sep.setVisible(True)
        for op in named_ops:
            btn = QPushButton(op.upper())
            btn.setFixedHeight(26)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, name=op: self._on_operator_filter_clicked(name))
            self._operator_filter_layout.addWidget(btn)
            self._operator_filter_buttons[op] = btn

    def _clear_operator_filter_buttons(self):
        """清除所有运营商筛选按钮。"""
        self._current_operator_filter = None
        for btn in self._operator_filter_buttons.values():
            self._operator_filter_layout.removeWidget(btn)
            btn.deleteLater()
        self._operator_filter_buttons.clear()
        self._operator_sep.setVisible(False)

    # ---------- 国家/服务器筛选 ----------

    def _on_completer_activated(self, text: str):
        idx = self.country_combo.findText(text)
        if idx >= 0:
            self.country_combo.setCurrentIndex(idx)

    def _on_refresh_countries(self):
        self.refresh_countries_btn.setEnabled(False)
        self.refresh_countries_btn.setText("...")
        self.refresh_countries_requested.emit()

    def set_countries(self, countries: list):
        self.refresh_countries_btn.setEnabled(True)
        self.refresh_countries_btn.setText("刷新")
        self.country_combo.blockSignals(True)
        self.country_combo.clear()
        self.country_combo.addItem("-- 请选择国家 --")
        labels = ["-- 请选择国家 --"]
        for c in countries:
            cid = c.get("id", 0)
            name = c.get("chn", "") or c.get("eng", "") or c.get("name", f"ID:{cid}")
            iso_code = str(
                c.get("iso", "") or c.get("short_name", "") or c.get("iso2", "")
            ).strip().upper()
            phone_code = str(
                c.get("code", "") or c.get("phone_code", "") or c.get("phoneCode", "")
            ).strip().lstrip("+")
            if iso_code:
                label = f"{iso_code} - {name} (ID:{cid})"
            else:
                label = f"{name} (ID:{cid})"
            labels.append(label)
            self.country_combo.addItem(label, {
                "country": name,
                "country_code": phone_code,
                "hero_country_id": cid,
            })
        self.country_combo.blockSignals(False)
        self._country_completer.setModel(QStringListModel(labels))
        self.server_list.clear()

        # 恢复上次选择的国家
        last_id = self.config.get("settings", {}).get("last_country_id")
        if last_id is not None:
            for i in range(1, self.country_combo.count()):
                item_data = self.country_combo.itemData(i)
                if isinstance(item_data, dict) and item_data.get("hero_country_id") == last_id:
                    self.country_combo.setCurrentIndex(i)
                    break

    def _on_country_changed(self, index: int):
        self.server_list.clear()
        self.operator_list.clear()
        if index <= 0:
            self.country_group.set_summary("")
            # 清除保存的国家选择
            self.config.setdefault("settings", {}).pop("last_country_id", None)
            save_config(self.config)
            return

        data = self.country_combo.currentData()
        if not data or not isinstance(data, dict):
            return

        # 保存选择的国家到配置
        self.config.setdefault("settings", {})["last_country_id"] = data.get("hero_country_id", 0)
        save_config(self.config)

        # 折叠国家组并显示摘要
        country_text = self.country_combo.currentText()
        self.country_group.set_summary(country_text)

        target_country = data.get("country", "").lower()

        # 填充服务器列表时屏蔽 itemChanged 信号，防止递归重绘
        self.server_list.blockSignals(True)
        servers = self.config.get("eims_servers", [])
        for idx, srv in enumerate(servers):
            if target_country:
                has_line = any(
                    line.get("herosms_country", "").lower() == target_country
                    for line in srv.get("lines", [])
                )
                if not has_line:
                    continue

            # 取匹配当前国家的线路名作为显示名
            line_name = srv.get("name", f"服务器 {idx + 1}")
            for line in srv.get("lines", []):
                if target_country and line.get("herosms_country", "").lower() == target_country:
                    line_name = line.get("country", "") or line_name
                    break
            item = QListWidgetItem(line_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, idx)
            self.server_list.addItem(item)
        self.server_list.blockSignals(False)

        self._update_server_summary()

        # 自动加载该国家的运营商
        self.load_operators_btn.setEnabled(False)
        self.load_operators_btn.setText("...")
        self.load_operators_requested.emit(data)

    def refresh_accounts(self):
        self.server_list.clear()

    # ---------- EIMS 服务器勾选管理 ----------

    def _update_server_summary(self):
        total = self.server_list.count()
        checked = sum(
            1 for i in range(total)
            if self.server_list.item(i).checkState() == Qt.CheckState.Checked
        )
        self.server_summary_label.setText(f"已选 {checked}/{total}")
        self.server_group.set_summary(f"{checked}/{total}")

    def _on_select_all_servers(self):
        self.server_list.blockSignals(True)
        for i in range(self.server_list.count()):
            self.server_list.item(i).setCheckState(Qt.CheckState.Checked)
        self.server_list.blockSignals(False)
        self._update_server_summary()

    def _on_deselect_all_servers(self):
        self.server_list.blockSignals(True)
        for i in range(self.server_list.count()):
            self.server_list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.server_list.blockSignals(False)
        self._update_server_summary()

    def get_checked_servers(self) -> list:
        result = []
        for i in range(self.server_list.count()):
            item = self.server_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(Qt.ItemDataRole.UserRole))
        return result

    # ---------- 运营商管理 ----------

    def _on_load_operators(self):
        country_data = self.country_combo.currentData()
        if not country_data or not isinstance(country_data, dict):
            QMessageBox.warning(self, "提示", "请先选择国家")
            return
        self.load_operators_btn.setEnabled(False)
        self.load_operators_btn.setText("...")
        self.load_operators_requested.emit(country_data)

    def set_operators(self, operators: list):
        self.load_operators_btn.setEnabled(True)
        self.load_operators_btn.setText("加载")

        existing = set()
        for i in range(self.operator_list.count()):
            item = self.operator_list.item(i)
            existing.add(item.text())

        for op in operators:
            name = op if isinstance(op, str) else str(op)
            if name and name not in existing:
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.operator_list.addItem(item)
                existing.add(name)

    def _on_add_operator(self):
        text = self.operator_input.text().strip()
        if not text:
            return
        for i in range(self.operator_list.count()):
            if self.operator_list.item(i).text() == text:
                QMessageBox.information(self, "提示", f"运营商 '{text}' 已存在")
                return
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        self.operator_list.addItem(item)
        self.operator_input.clear()

    def _on_select_all_operators(self):
        for i in range(self.operator_list.count()):
            self.operator_list.item(i).setCheckState(Qt.CheckState.Checked)

    def _on_deselect_all_operators(self):
        for i in range(self.operator_list.count()):
            self.operator_list.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _on_remove_checked_operators(self):
        rows_to_remove = []
        for i in range(self.operator_list.count()):
            if self.operator_list.item(i).checkState() == Qt.CheckState.Checked:
                rows_to_remove.append(i)
        for i in reversed(rows_to_remove):
            self.operator_list.takeItem(i)

    def get_checked_operators(self) -> list:
        result = []
        for i in range(self.operator_list.count()):
            item = self.operator_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.text())
        return result

    # ---------- 开始/停止 ----------

    def _on_start(self):
        servers = self.get_checked_servers()
        if not servers:
            QMessageBox.warning(self, "提示", "请至少勾选一条 EIMS 线路")
            return
        hero = self.config.get("herosms", {})
        if not hero.get("api_key"):
            QMessageBox.warning(self, "提示", "请先在账号管理中配置 HeroSMS API Key")
            return

        country_data = self.country_combo.currentData()
        if not country_data or not isinstance(country_data, dict):
            QMessageBox.warning(self, "提示", "请先选择国家")
            return

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.retest_btn.setEnabled(False)
        self.recheck_btn.setEnabled(False)
        self._success_count = 0
        self._fail_count = 0
        self._update_counters()
        self.progress_label.setText("检测中...")

        operators = self.get_checked_operators()

        params = {
            "eims_servers": servers,
            "country": country_data.get("country", ""),
            "country_code": country_data.get("country_code", ""),
            "hero_country_id": country_data.get("hero_country_id", 0),
            "service": "ot",
            "content": "test",
            "timeout": self.timeout_spin.value(),
            "operators": operators,
        }
        logger.debug("即将发射 start_requested, params keys=%s", list(params.keys()))
        self.start_requested.emit(params)

    def _on_stop(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.retest_btn.setEnabled(True)
        self.recheck_btn.setEnabled(True)
        self.progress_label.setText("已停止")
        self.stop_requested.emit()

    def _on_retest(self):
        self.retest_btn.setEnabled(False)
        self.recheck_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_label.setText("重新测试中...")
        self.retest_requested.emit()

    def _on_recheck(self):
        self.recheck_btn.setEnabled(False)
        self.progress_label.setText("落地查询中...")
        self.recheck_requested.emit()

    def set_running(self, running: bool):
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        if running:
            self.retest_btn.setEnabled(False)
            self.recheck_btn.setEnabled(False)
            self.progress_label.setText("检测中...")
        else:
            self.retest_btn.setEnabled(True)
            self.recheck_btn.setEnabled(True)
            self.progress_label.setText("已完成")

    # ---------- 扁平化表格操作 ----------

    def setup_result_table(self, server_names: list[str], operators: list[str]):
        """根据服务器和运营商列表创建扁平化表格。

        每行 = 一个 (服务器, 运营商) 组合。
        行数 = len(server_names) * len(operators)。
        行映射: row = srv_idx * num_ops + op_idx。
        """
        self._current_operators = list(operators)
        self._num_servers = len(server_names)
        self._num_operators = len(operators)
        total_rows = self._num_servers * self._num_operators

        self.result_table.clear()
        self.result_table.setColumnCount(self.TOTAL_COLS)
        self.result_table.setHorizontalHeaderLabels(self.HEADERS)
        self.result_table.setRowCount(total_rows)

        # 列宽策略
        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_SEQ, QHeaderView.ResizeMode.Fixed)
        self.result_table.setColumnWidth(self.COL_SEQ, 46)
        self.result_table.setColumnWidth(self.COL_SERVER, 120)
        self.result_table.setColumnWidth(self.COL_OPERATOR, 90)
        self.result_table.setColumnWidth(self.COL_PHONE, 120)
        self.result_table.setColumnWidth(self.COL_SEND, 90)
        self.result_table.setColumnWidth(self.COL_DELIVER, 90)
        self.result_table.setColumnWidth(self.COL_LANDED, 100)
        self.result_table.setColumnWidth(self.COL_ELAPSED, 60)
        header.setSectionResizeMode(self.COL_REASON, QHeaderView.ResizeMode.Stretch)

        # 设置行高
        self.result_table.verticalHeader().setDefaultSectionSize(28)

        # 批量填充行时禁用更新，防止逐行重绘
        self.result_table.setUpdatesEnabled(False)
        seq = 1
        for si, srv_name in enumerate(server_names):
            bg_color = QColor(self._SERVER_COLORS[si % len(self._SERVER_COLORS)])
            for oi, op in enumerate(operators):
                row = si * self._num_operators + oi
                display_op = "任意" if op == "any" else op.upper()

                items_data = [
                    (self.COL_SEQ, str(seq)),
                    (self.COL_SERVER, srv_name),
                    (self.COL_OPERATOR, display_op),
                    (self.COL_PHONE, "-"),
                    (self.COL_SEND, "-"),
                    (self.COL_DELIVER, "-"),
                    (self.COL_LANDED, "-"),
                    (self.COL_ELAPSED, "-"),
                    (self.COL_REASON, "-"),
                ]
                for col, text in items_data:
                    item = QTableWidgetItem(text)
                    item.setBackground(bg_color)
                    self.result_table.setItem(row, col, item)
                seq += 1

        self.result_table.setUpdatesEnabled(True)
        self.result_table.viewport().update()
        self.progress_bar.setRange(0, total_rows)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"0/{total_rows}")

        self._success_count = 0
        self._fail_count = 0
        self._update_counters()
        self._current_filter = "all"
        for k, btn in self._filter_buttons.items():
            btn.setChecked(k == "all")

        # 动态生成运营商筛选按钮
        self._setup_operator_filter_buttons(operators)

    def _get_row(self, srv_idx: int, op_idx: int) -> int:
        """将 (srv_idx, op_idx) 映射到表格行号。"""
        return srv_idx * self._num_operators + op_idx

    def update_cell(self, srv_idx: int, op_idx: int, field: str, value: str):
        """更新扁平化表格中指定单元格。

        Args:
            srv_idx: 服务器索引
            op_idx: 运营商索引
            field: "send" | "deliver" | "landed" | "reason" | "phone" | "elapsed"
            value: 显示文本
        """
        row = self._get_row(srv_idx, op_idx)
        if row < 0 or row >= self.result_table.rowCount():
            return

        col_map = {
            "send": self.COL_SEND,
            "deliver": self.COL_DELIVER,
            "landed": self.COL_LANDED,
            "reason": self.COL_REASON,
            "phone": self.COL_PHONE,
            "elapsed": self.COL_ELAPSED,
        }
        col = col_map.get(field)
        if col is None:
            return

        # 完全冻结表格视觉更新，防止 setItem 触发布局重算/重绘
        self.result_table.setUpdatesEnabled(False)
        self.result_table.blockSignals(True)
        try:
            # 保持行背景色
            existing = self.result_table.item(row, self.COL_SEQ)
            bg_color = existing.background().color() if existing else QColor("#FFFFFF")

            item = QTableWidgetItem(value)
            item.setBackground(bg_color)

            # 状态着色
            if field == "landed":
                if "已落地" in value:
                    item.setForeground(QColor("#047857"))
                    item.setBackground(QColor("#D1FAE5"))
                elif "未落地" in value:
                    item.setForeground(QColor("#B91C1C"))
                    item.setBackground(QColor("#FEE2E2"))
                elif "检测中" in value or "查询中" in value or "重测中" in value:
                    item.setForeground(QColor("#92400E"))
                    item.setBackground(QColor("#FEF3C7"))
                elif "已停止" in value:
                    item.setForeground(QColor("#334155"))
                    item.setBackground(QColor("#E2E8F0"))
                elif "失败" in value or "取号失败" in value:
                    item.setForeground(QColor("#44403C"))
                    item.setBackground(QColor("#E7E5E4"))
            elif field == "send":
                if "已发送" in value or "已提交" in value:
                    item.setForeground(QColor("#10B981"))
                elif "失败" in value or "异常" in value or "取号失败" in value:
                    item.setForeground(QColor("#EF4444"))
            elif field == "deliver":
                if "已送达" in value:
                    item.setForeground(QColor("#10B981"))
                elif "失败" in value:
                    item.setForeground(QColor("#EF4444"))
            elif field == "reason":
                if value and value != "-" and value != "":
                    item.setForeground(QColor("#EF4444"))

            self.result_table.setItem(row, col, item)
        finally:
            self.result_table.blockSignals(False)
            self.result_table.setUpdatesEnabled(True)
            self.result_table.viewport().repaint()

        # 时间戳节流刷新统计
        if field == "landed":
            now = time.time()
            if now - self._last_refresh_time > 0.5:
                self._last_refresh_time = now
                self._do_refresh()

    def refresh_display(self):
        """刷新统计计数器和筛选状态。在检测完成后调用。"""
        self._do_refresh()

    def _do_refresh(self):
        """执行统计和筛选刷新，带守卫防止递归。"""
        if self._updating:
            return
        self._updating = True
        self.result_table.setUpdatesEnabled(False)
        try:
            self._update_counters()
            self._apply_filter()
        finally:
            self.result_table.setUpdatesEnabled(True)
            self.result_table.viewport().repaint()
            self._updating = False

    def _update_counters(self):
        """扫描表格统计各状态数量，更新标签和进度条。"""
        landed = 0
        not_landed = 0
        testing = 0
        failed = 0
        total = self.result_table.rowCount()

        for row in range(total):
            item = self.result_table.item(row, self.COL_LANDED)
            if not item:
                continue
            text = item.text()
            if "已落地" in text:
                landed += 1
            elif "未落地" in text:
                not_landed += 1
            elif "检测中" in text or "查询中" in text or "重测中" in text:
                testing += 1
            elif "失败" in text or "已停止" in text or "取号失败" in text:
                failed += 1

        self._success_count = landed
        self._fail_count = not_landed + failed

        self._update_stat_badge(self.landed_label, landed)
        self._update_stat_badge(self.not_landed_label, not_landed)
        self._update_stat_badge(self.testing_label, testing)
        self._update_stat_badge(self.failed_label, failed)

        # 进度条：已完成 = 已落地 + 未落地 + 失败（不含检测中）
        completed = landed + not_landed + failed
        self.progress_bar.setValue(completed)
        self.progress_bar.setFormat(f"{completed}/{total}")

    def clear_results(self):
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(self.TOTAL_COLS)
        self.result_table.setHorizontalHeaderLabels(self.HEADERS)
        self._current_operators = []
        self._num_servers = 0
        self._num_operators = 0
        self._success_count = 0
        self._fail_count = 0
        self._clear_operator_filter_buttons()
        self._update_counters()
        self.progress_label.setText("就绪")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0/0")

    def update_phone_cache_display(self, cache_list: list):
        """刷新活跃号码缓存列表显示。"""
        import time as _time
        self.cache_list.clear()
        now = _time.time()
        for item in cache_list:
            remaining = max(0, 20 * 60 - (now - item["time"]))
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            text = f"{item['operator']}: {item['phone']} ({mins}:{secs:02d})"
            self.cache_list.addItem(text)
        count = len(cache_list)
        self.cache_summary_label.setText(
            f"{count} 个活跃号码" if count else "无缓存号码"
        )
        self.cache_group.set_summary(f"{count}" if count else "")

