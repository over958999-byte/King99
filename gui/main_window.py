from PySide6.QtWidgets import QMainWindow, QTabWidget, QStatusBar, QApplication
from PySide6.QtCore import QObject, QThread, Signal, Slot, QTimer

from utils.config_loader import load_config
from gui.account_tab import AccountTab
from gui.detection_tab import DetectionTab
from gui.log_tab import LogTab
from api.eims_client import EIMSClient, get_status_message
from api.herosms_client import HeroSMSClient, HeroSMSError


class _NetworkWorker(QObject):
    """在子线程中执行网络请求的通用 Worker。"""

    finished = Signal(object)  # 成功时发射结果
    error = Signal(Exception)  # 失败时发射异常

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    @Slot()
    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(e)


class MainWindow(QMainWindow):
    """困King落地助手 - 主窗口。"""

    def __init__(self, config: dict = None):
        super().__init__()
        self.config = config or load_config()
        self._net_threads: list[tuple[QThread, QObject]] = []  # 保留 (thread, worker) 引用
        self._dead_threads: list[tuple[QThread, QObject]] = []  # 已完成待清理的线程
        self.setWindowTitle("困King落地助手")
        self.setMinimumSize(900, 600)
        self._init_ui()
        self._init_engine()
        self._adapt_window_size()
        self._on_refresh_countries()
        # 启动后自动测试所有 EIMS 服务器连接
        QTimer.singleShot(500, self._auto_test_all_servers)
        # 启动后自动查询 HeroSMS 余额
        QTimer.singleShot(800, self._on_query_balance)

    def _init_ui(self):
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.setCentralWidget(self.tabs)

        # Tab 1: 账号管理
        self.account_tab = AccountTab(self.config)
        self.tabs.addTab(self.account_tab, "\u2699  账号管理")

        # Tab 2: 落地检测
        self.detection_tab = DetectionTab(self.config)
        self.tabs.addTab(self.detection_tab, "\u25B6  落地检测")

        # Tab 3: 日志
        self.log_tab = LogTab()
        self.tabs.addTab(self.log_tab, "\u2630  日志")

        # 账号变更时刷新
        self.account_tab.config_changed.connect(self._on_config_changed)

        # 账号管理页的测试/查余额
        self.account_tab.test_eims_requested.connect(self._on_test_eims)
        self.account_tab.query_balance_requested.connect(self._on_query_balance)

        # 落地检测页的加载运营商和刷新国家
        self.detection_tab.load_operators_requested.connect(self._on_load_operators)
        self.detection_tab.refresh_countries_requested.connect(self._on_refresh_countries)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def _init_engine(self):
        """创建检测引擎并连接 GUI 信号。"""
        from core.detection_engine import DetectionEngine
        self._engine = DetectionEngine(self)

    def _adapt_window_size(self):
        """根据屏幕尺寸自适应窗口大小并居中显示。"""
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1200, 800)
            return
        avail = screen.availableGeometry()
        w = int(avail.width() * 0.8)
        h = int(avail.height() * 0.75)
        self.resize(w, h)
        x = avail.x() + (avail.width() - w) // 2
        y = avail.y() + (avail.height() - h) // 2
        self.move(x, y)

    def _run_in_thread(self, func, on_success, on_error, *args, **kwargs):
        """在子线程中执行 func，完成后在主线程回调 on_success/on_error。"""
        # 先清理已完成的旧线程
        self._cleanup_dead_threads()

        thread = QThread()
        worker = _NetworkWorker(func, *args, **kwargs)
        worker.moveToThread(thread)

        pair = (thread, worker)
        cleaned = False

        def _cleanup():
            nonlocal cleaned
            if cleaned:
                return
            cleaned = True
            # 移到待清理列表，保留引用防止 GC
            if pair in self._net_threads:
                self._net_threads.remove(pair)
            self._dead_threads.append(pair)
            thread.quit()
            # 延迟清理，让线程有时间退出
            QTimer.singleShot(500, self._cleanup_dead_threads)

        thread.started.connect(worker.run)
        worker.finished.connect(on_success)
        worker.finished.connect(_cleanup)
        worker.error.connect(on_error)
        worker.error.connect(_cleanup)

        self._net_threads.append(pair)
        thread.start()

    def _cleanup_dead_threads(self):
        """清理已完成的线程，只清理确认已停止的。"""
        still_alive = []
        for thread, worker in self._dead_threads:
            if thread.isRunning():
                still_alive.append((thread, worker))
            # 已停止的线程：不调用 deleteLater，让 Python GC 自然回收
        self._dead_threads = still_alive

    def closeEvent(self, event):
        """程序关闭时安全停止所有线程。"""
        # 停止检测引擎
        if hasattr(self, '_engine'):
            self._engine.shutdown()

        # 停止所有网络请求线程
        all_threads = self._net_threads + self._dead_threads
        for thread, _worker in all_threads:
            if thread.isRunning():
                thread.quit()
        # 等待所有线程退出
        for thread, _worker in all_threads:
            if thread.isRunning():
                thread.wait(3000)
        super().closeEvent(event)

    def _on_config_changed(self):
        self.config = load_config()
        self.detection_tab.config = self.config
        self.detection_tab.refresh_accounts()
        self.status_bar.showMessage("配置已更新")
        self.log_tab.append_log("配置已更新并保存")

    @Slot()
    def _on_refresh_countries(self):
        """从 HeroSMS API 获取国家列表（子线程）。"""
        hero = self.config.get("herosms", {})
        api_key = hero.get("api_key", "")
        if not api_key:
            self.detection_tab.set_countries([])
            self.log_tab.append_log("加载国家列表失败: 未配置 HeroSMS API Key")
            self.status_bar.showMessage("请先在「账号管理」中配置 HeroSMS API Key")
            return

        self.log_tab.append_log("正在从 HeroSMS 加载国家列表...")
        self.status_bar.showMessage("加载国家列表中...")

        def _fetch():
            client = HeroSMSClient(
                api_key=api_key,
                base_url=hero.get(
                    "base_url", "https://hero-sms.com/stubs/handler_api.php"
                ),
                timeout=15,
            )
            return client.get_countries()

        def _on_ok(countries):
            self.detection_tab.set_countries(countries)
            self.log_tab.append_log(f"已加载 {len(countries)} 个国家")
            self.status_bar.showMessage(f"已加载 {len(countries)} 个国家")

        def _on_err(e):
            self.detection_tab.set_countries([])
            msg = e.message if isinstance(e, HeroSMSError) else str(e)
            self.log_tab.append_log(f"加载国家列表失败: {msg}")
            self.status_bar.showMessage(f"加载国家列表失败: {msg}")

        self._run_in_thread(_fetch, _on_ok, _on_err)

    # ---------- 账号管理功能 ----------

    @Slot(int)
    def _on_test_eims(self, row: int):
        """测试 EIMS 服务器连接（子线程）。"""
        servers = self.config.get("eims_servers", [])
        if row < 0 or row >= len(servers):
            return
        srv = servers[row]
        self.account_tab.update_eims_status(row, "测试中...")
        self.log_tab.append_log(f"测试 EIMS 连接: {srv.get('name', '')}")

        def _fetch():
            client = EIMSClient(
                host=srv.get("host", ""),
                port=srv.get("port", 20003),
                account=srv.get("username", ""),
                password=srv.get("password", ""),
                use_md5=srv.get("md5_auth", False),
                protocol_key=srv.get("protocol_key", ""),
                timeout=10,
            )
            return client.get_balance()

        def _on_ok(resp):
            status = resp.get("status", -99)
            if status == 0:
                balance = resp.get("balance", "0")
                self.account_tab.update_eims_status(row, f"正常 (余额:{balance})")
                self.log_tab.append_log(f"EIMS 连接成功, 余额: {balance}")
            else:
                msg = get_status_message(status)
                self.account_tab.update_eims_status(row, f"错误: {msg}")
                self.log_tab.append_log(f"EIMS 连接错误: {msg}")

        def _on_err(e):
            self.account_tab.update_eims_status(row, "连接失败")
            self.log_tab.append_log(f"EIMS 连接失败: {e}")

        self._run_in_thread(_fetch, _on_ok, _on_err)

    def _auto_test_all_servers(self):
        """启动后自动测试所有 EIMS 服务器连接状态。"""
        servers = self.config.get("eims_servers", [])
        if not servers:
            return
        self._auto_test_total = len(servers)
        self._auto_test_done = 0
        self._auto_test_ok = 0
        self.status_bar.showMessage(f"正在测试 EIMS 服务器连接 (0/{self._auto_test_total})...")
        self.log_tab.append_log(f"自动测试 {len(servers)} 个 EIMS 服务器连接...")

        for row, srv in enumerate(servers):
            self.account_tab.update_eims_status(row, "测试中...")

            def _make_fetch(s):
                def _fetch():
                    client = EIMSClient(
                        host=s.get("host", ""),
                        port=s.get("port", 20003),
                        account=s.get("username", ""),
                        password=s.get("password", ""),
                        use_md5=s.get("md5_auth", False),
                        protocol_key=s.get("protocol_key", ""),
                        timeout=10,
                    )
                    return client.get_balance()
                return _fetch

            def _make_on_ok(r, name):
                def _on_ok(resp):
                    status = resp.get("status", -99)
                    if status == 0:
                        balance = resp.get("balance", "0")
                        self.account_tab.update_eims_status(r, f"正常 (余额:{balance})")
                        self._auto_test_ok += 1
                    else:
                        msg = get_status_message(status)
                        self.account_tab.update_eims_status(r, f"错误: {msg}")
                    self._auto_test_done += 1
                    self._update_auto_test_progress()
                return _on_ok

            def _make_on_err(r, name):
                def _on_err(e):
                    self.account_tab.update_eims_status(r, "连接失败")
                    self.log_tab.append_log(f"[{name}] 连接失败: {e}")
                    self._auto_test_done += 1
                    self._update_auto_test_progress()
                return _on_err

            name = srv.get("name", f"服务器{row+1}")
            self._run_in_thread(_make_fetch(srv), _make_on_ok(row, name), _make_on_err(row, name))

    def _update_auto_test_progress(self):
        """更新自动测试进度。"""
        done = self._auto_test_done
        total = self._auto_test_total
        if done < total:
            self.status_bar.showMessage(f"正在测试 EIMS 服务器连接 ({done}/{total})...")
        else:
            ok = self._auto_test_ok
            fail = total - ok
            self.status_bar.showMessage(f"EIMS 服务器测试完成: {ok} 个正常, {fail} 个异常")
            self.log_tab.append_log(f"EIMS 服务器自动测试完成: {ok}/{total} 正常")

    @Slot()
    def _on_query_balance(self):
        """查询 HeroSMS 余额（子线程）。"""
        hero = self.config.get("herosms", {})
        api_key = hero.get("api_key", "")
        if not api_key:
            self.account_tab.update_hero_status("未配置 API Key")
            return
        self.account_tab.update_hero_status("查询中...")
        self.log_tab.append_log("查询 HeroSMS 余额")

        def _fetch():
            client = HeroSMSClient(
                api_key=api_key,
                base_url=hero.get(
                    "base_url", "https://hero-sms.com/stubs/handler_api.php"
                ),
                timeout=10,
            )
            return client.get_balance()

        def _on_ok(balance):
            self.account_tab.update_hero_balance(f"{balance:.2f}")
            self.log_tab.append_log(f"HeroSMS 余额: {balance:.2f}")

        def _on_err(e):
            if isinstance(e, HeroSMSError):
                self.account_tab.update_hero_status(f"错误: {e.message}")
                self.log_tab.append_log(f"HeroSMS 余额查询错误: {e.message}")
            else:
                self.account_tab.update_hero_status("查询失败")
                self.log_tab.append_log(f"HeroSMS 余额查询失败: {e}")

        self._run_in_thread(_fetch, _on_ok, _on_err)

    @Slot(str)
    def update_status(self, message: str):
        self.status_bar.showMessage(message)

    def log(self, message: str):
        self.log_tab.append_log(message)

    # ---------- 运营商加载 ----------

    @staticmethod
    def _extract_operators(data) -> list[str]:
        """从 getOperators API 返回数据中提取运营商名称列表。

        API 文档格式: {"status":"success","countryOperators":{"175":["optus","vodafone",...]}}
        """
        _META_KEYS = {"status", "error", "msg", "message", "code"}
        operators = []

        def _add(name: str):
            if name and name not in operators:
                operators.append(name)

        if not isinstance(data, dict):
            # 极少见：直接返回列表
            if isinstance(data, list):
                for item in data:
                    _add(item if isinstance(item, str) else str(item))
            return operators

        # 标准格式：countryOperators -> {country_id: [op_names]}
        country_ops = data.get("countryOperators")
        if isinstance(country_ops, dict):
            for _cid, op_val in country_ops.items():
                if isinstance(op_val, list):
                    for op in op_val:
                        _add(op if isinstance(op, str) else str(op))
                elif isinstance(op_val, dict):
                    for op_name in op_val:
                        _add(op_name)
            if operators:
                return operators

        # 兜底：遍历所有非 meta key
        for key, value in data.items():
            if key.lower() in _META_KEYS or key == "countryOperators":
                continue
            if isinstance(value, list):
                for op in value:
                    _add(op if isinstance(op, str) else str(op))
            elif isinstance(value, dict):
                # value 可能是 {country_id: [ops]} 再嵌套一层
                for sub_key, sub_val in value.items():
                    if isinstance(sub_val, list):
                        for op in sub_val:
                            _add(op if isinstance(op, str) else str(op))
                    elif isinstance(sub_val, str):
                        _add(sub_val)

        return operators

    @Slot(dict)
    def _on_load_operators(self, country_data: dict):
        """根据国家加载运营商列表（子线程）。

        country_data 格式: {"country": "Chile", "country_code": "39", "hero_country_id": 39}
        使用 hero_country_id 调用 get_operators(country=id) 获取该国家的运营商。
        """
        hero = self.config.get("herosms", {})
        api_key = hero.get("api_key", "")
        if not api_key:
            self.detection_tab.set_operators([])
            self.log_tab.append_log("加载运营商失败: 未配置 HeroSMS API Key")
            return

        country_name = country_data.get("country", "")
        hero_country_id = country_data.get("hero_country_id", 0)
        self.log_tab.append_log(
            f"正在加载运营商列表: 国家={country_name} (ID:{hero_country_id})"
        )
        self.status_bar.showMessage(f"加载运营商列表: {country_name}...")

        def _fetch():
            client = HeroSMSClient(
                api_key=api_key,
                base_url=hero.get(
                    "base_url", "https://hero-sms.com/stubs/handler_api.php"
                ),
                timeout=15,
            )
            return client.get_operators(country=hero_country_id)

        def _on_ok(data):
            self.log_tab.append_log(f"[DEBUG] getOperators 原始返回: {data}")
            operators = self._extract_operators(data)
            self.detection_tab.set_operators(operators)
            self.log_tab.append_log(
                f"已加载 {len(operators)} 个运营商: "
                f"{', '.join(operators) if operators else '(无)'}"
            )
            self.status_bar.showMessage(
                f"已加载 {len(operators)} 个运营商 ({country_name})"
            )

        def _on_err(e):
            self.detection_tab.set_operators([])
            msg = e.message if isinstance(e, HeroSMSError) else str(e)
            self.log_tab.append_log(f"加载运营商失败: {msg}")
            self.status_bar.showMessage(f"加载运营商失败: {msg}")

        self._run_in_thread(_fetch, _on_ok, _on_err)
