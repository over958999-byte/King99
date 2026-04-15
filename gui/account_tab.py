import json
import re
from datetime import date

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QDialogButtonBox, QFormLayout, QLineEdit, QSpinBox, QCheckBox,
    QMessageBox, QLabel, QSplitter, QPlainTextEdit, QFileDialog,
)
from PySide6.QtCore import Signal, Qt

from utils.config_loader import load_config, save_config


# ---------- 对话框 ----------

class EimsServerDialog(QDialog):
    """EIMS 服务器编辑对话框。"""

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle("EIMS 服务器配置")
        self.setMinimumWidth(400)
        self._existing_lines = []

        layout = QFormLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.name_edit = QLineEdit()
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("IP 地址")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(20003)
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.md5_check = QCheckBox("启用")
        self.protocol_key_edit = QLineEdit()
        self.protocol_key_edit.setPlaceholderText("留空则使用默认值")
        self.charge_rule_edit = QLineEdit()
        self.charge_rule_edit.setPlaceholderText("如: Submit billing")

        layout.addRow("名称:", self.name_edit)
        layout.addRow("IP 地址:", self.host_edit)
        layout.addRow("端口:", self.port_spin)
        layout.addRow("账号:", self.username_edit)
        layout.addRow("密码:", self.password_edit)
        layout.addRow("MD5 认证:", self.md5_check)
        layout.addRow("协议 Key:", self.protocol_key_edit)
        layout.addRow("计费规则:", self.charge_rule_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        if data:
            self.name_edit.setText(data.get("name", ""))
            self.host_edit.setText(data.get("host", ""))
            self.port_spin.setValue(data.get("port", 20003))
            self.username_edit.setText(data.get("username", ""))
            self.password_edit.setText(data.get("password", ""))
            self.md5_check.setChecked(data.get("md5_auth", False))
            self.protocol_key_edit.setText(data.get("protocol_key", ""))
            self.charge_rule_edit.setText(data.get("charge_rule", ""))
            self._existing_lines = list(data.get("lines", []))

    def get_data(self) -> dict:
        return {
            "name": self.name_edit.text(),
            "host": self.host_edit.text(),
            "port": self.port_spin.value(),
            "username": self.username_edit.text(),
            "password": self.password_edit.text(),
            "md5_auth": self.md5_check.isChecked(),
            "protocol_key": self.protocol_key_edit.text(),
            "charge_rule": self.charge_rule_edit.text().strip(),
            "lines": self._existing_lines,
        }


class LineDialog(QDialog):
    """线路编辑对话框。"""

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle("线路配置")
        self.setMinimumWidth(340)

        layout = QFormLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.country_edit = QLineEdit()
        self.country_edit.setPlaceholderText("如: 美国")
        self.country_code_edit = QLineEdit()
        self.country_code_edit.setPlaceholderText("如: 1")
        self.herosms_country_edit = QLineEdit()
        self.herosms_country_edit.setPlaceholderText("如: United States")
        self.remark_edit = QLineEdit()
        self.remark_edit.setPlaceholderText("如: T-Mobile线路")

        layout.addRow("线路名:", self.country_edit)
        layout.addRow("国家区号:", self.country_code_edit)
        layout.addRow("HeroSMS国家:", self.herosms_country_edit)
        layout.addRow("备注:", self.remark_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        if data:
            self.country_edit.setText(data.get("country", ""))
            self.country_code_edit.setText(data.get("country_code", ""))
            self.herosms_country_edit.setText(data.get("herosms_country", ""))
            self.remark_edit.setText(data.get("remark", ""))

    def get_data(self) -> dict:
        return {
            "country": self.country_edit.text().strip(),
            "country_code": self.country_code_edit.text().strip(),
            "herosms_country": self.herosms_country_edit.text().strip(),
            "remark": self.remark_edit.text().strip(),
        }


class BatchImportDialog(QDialog):
    """EIMS 服务器批量导入对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量导入 EIMS 服务器")
        self.setMinimumSize(520, 420)
        self._parsed_servers = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        hint = QLabel(
            "粘贴多个服务器的配置信息（每组之间用空行分隔）。\n"
            "支持格式如: Username / Auth Password / SMPP Server / HTTP Port / Charge Rule 等"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748B; font-size: 12px; padding: 4px 0;")
        layout.addWidget(hint)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "Username: pppppp\n"
            "Auth Password: 4C9B2842\n"
            "SMPP Version 3.4\n"
            "SMPP Server: 8.218.246.144\n"
            "SMPP Port: 20002\n"
            "HTTP Port: 20003\n"
            "Charge Rule: Submit billing\n"
            "\n"
            "Username: qqqqqq\n"
            "Auth Password: ABCD1234\n"
            "..."
        )
        layout.addWidget(self.text_edit)

        self.preview_label = QLabel("解析到 0 个服务器")
        self.preview_label.setStyleSheet("font-weight: bold; color: #2563EB; font-size: 13px;")
        layout.addWidget(self.preview_label)

        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("color: #64748B; font-size: 11px;")
        layout.addWidget(self.detail_label)

        self.text_edit.textChanged.connect(self._on_text_changed)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        self.import_btn = QPushButton("确认导入")
        self.import_btn.setProperty("class", "primary")
        self.import_btn.setEnabled(False)
        self.cancel_btn = QPushButton("取消")
        btn_layout.addStretch()
        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self.import_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def _on_text_changed(self):
        self._parsed_servers = self._parse_all()
        count = len(self._parsed_servers)
        self.preview_label.setText(f"解析到 {count} 个服务器")
        self.import_btn.setEnabled(count > 0)

        if count > 0:
            names = [s.get("name", "?") for s in self._parsed_servers[:10]]
            detail = "、".join(names)
            if count > 10:
                detail += f" ... 等共 {count} 个"
            self.detail_label.setText(detail)
        else:
            self.detail_label.setText("")

    def _parse_all(self) -> list:
        text = self.text_edit.toPlainText().strip()
        if not text:
            return []

        # 全角冒号统一替换为半角冒号
        text = text.replace('\uff1a', ':')

        # 先按连续空行分割为多组（兼容 \r\n 换行）
        raw_groups = re.split(r'(?:\r?\n)\s*(?:\r?\n)', text)

        # 再对每组内部检测重复 Username: 进行二次拆分
        groups = []
        for raw in raw_groups:
            raw = raw.strip()
            if not raw:
                continue
            sub_groups = self._split_by_repeated_key(raw, 'username')
            groups.extend(sub_groups)

        results = []
        for group in groups:
            parsed = self._parse_group(group)
            if parsed:
                results.append(parsed)
        return results

    @staticmethod
    def _split_by_repeated_key(text: str, key: str) -> list[str]:
        """当一组文本内出现多次同一关键字时，按该关键字拆分为多组。"""
        lines = text.splitlines()
        groups = []
        current = []
        key_lower = key.lower()
        for line in lines:
            stripped = line.strip().lower()
            # 检测该行是否以 "key:" 或 "key :" 开头
            if stripped.startswith(key_lower) and ':' in stripped:
                before_colon = stripped.split(':', 1)[0].strip()
                if before_colon == key_lower and current:
                    # 遇到重复的 key，把之前的行作为一组
                    groups.append('\n'.join(current))
                    current = []
            current.append(line)
        if current:
            groups.append('\n'.join(current))
        return groups

    @staticmethod
    def _parse_group(text: str) -> dict | None:
        """解析单组服务器配置文本。"""
        fields = {}
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if ':' in line:
                key, _, value = line.partition(':')
                fields[key.strip().lower()] = value.strip()
            else:
                # 无冒号的行，如 "SMPP Version 3.4"
                parts = line.rsplit(None, 1)
                if len(parts) == 2:
                    fields[parts[0].strip().lower()] = parts[1].strip()

        username = fields.get("username", "")
        host = fields.get("smpp server", "")
        if not username or not host:
            return None

        password = fields.get("auth password", "")

        # HTTP Port
        http_port = 20003
        raw_http = fields.get("http port", "")
        if raw_http.isdigit():
            http_port = int(raw_http)

        # SMPP Port
        smpp_port = 0
        raw_smpp = fields.get("smpp port", "")
        if raw_smpp.isdigit():
            smpp_port = int(raw_smpp)

        smpp_version = fields.get("smpp version", "")
        charge_rule = fields.get("charge rule", "")

        return {
            "name": f"{username}@{host}",
            "host": host,
            "port": http_port,
            "username": username,
            "password": password,
            "md5_auth": False,
            "protocol_key": "",
            "smpp_port": smpp_port,
            "smpp_version": smpp_version,
            "charge_rule": charge_rule,
            "lines": [],
        }

    def get_servers(self) -> list:
        return self._parsed_servers


class BatchImportLineDialog(QDialog):
    """线路批量导入对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量添加线路")
        self.setMinimumSize(480, 380)
        self._parsed_lines = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        hint = QLabel(
            "每行一条线路，格式：国家名称  区号  HeroSMS国家  备注\n"
            "字段之间用空格、Tab 或逗号分隔，HeroSMS国家和备注可省略。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748B; font-size: 12px; padding: 4px 0;")
        layout.addWidget(hint)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "美国  1  United States  T-Mobile线路\n"
            "英国  44  United Kingdom  Vodafone\n"
            "日本  81  Japan\n"
            "中国, 86, China, 移动线路"
        )
        layout.addWidget(self.text_edit)

        self.preview_label = QLabel("解析到 0 条线路")
        self.preview_label.setStyleSheet("font-weight: bold; color: #2563EB; font-size: 13px;")
        layout.addWidget(self.preview_label)

        self.text_edit.textChanged.connect(self._on_text_changed)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        self.import_btn = QPushButton("确认添加")
        self.import_btn.setProperty("class", "primary")
        self.import_btn.setEnabled(False)
        self.cancel_btn = QPushButton("取消")
        btn_layout.addStretch()
        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self.import_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def _on_text_changed(self):
        self._parsed_lines = self._parse_all()
        count = len(self._parsed_lines)
        self.preview_label.setText(f"解析到 {count} 条线路")
        self.import_btn.setEnabled(count > 0)

    def _parse_all(self) -> list:
        text = self.text_edit.toPlainText().strip()
        if not text:
            return []
        results = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = self._parse_line(line)
            if parsed:
                results.append(parsed)
        return results

    @staticmethod
    def _parse_line(line: str) -> dict | None:
        """解析单行线路数据。支持空格/Tab/逗号分隔。
        格式：国家名称  区号  [HeroSMS国家]  [备注]
        """
        # 统一分隔符：先按逗号拆，再按空白拆
        if ',' in line:
            parts = [p.strip() for p in line.split(',') if p.strip()]
        else:
            parts = line.split()
        if len(parts) < 2:
            return None
        country = parts[0]
        country_code = parts[1]
        herosms_country = parts[2] if len(parts) > 2 else ""
        remark = ' '.join(parts[3:]) if len(parts) > 3 else ""
        return {
            "country": country,
            "country_code": country_code,
            "herosms_country": herosms_country,
            "remark": remark,
        }

    def get_lines(self) -> list:
        return self._parsed_lines


# ---------- 主标签页 ----------

class AccountTab(QWidget):
    """账号管理标签页：左栏 EIMS 服务器+线路管理，右栏 HeroSMS 单账号表单。"""

    config_changed = Signal()
    test_eims_requested = Signal(int)
    query_balance_requested = Signal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._init_ui()
        self._load_accounts()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ===== 左栏：EIMS 服务器 + 线路 =====
        eims_group = QGroupBox("EIMS 服务器")
        eims_outer = QVBoxLayout(eims_group)
        eims_outer.setContentsMargins(10, 20, 10, 10)
        eims_outer.setSpacing(8)

        # -- 服务器表格 --
        self.eims_table = QTableWidget(0, 8)
        self.eims_table.setAlternatingRowColors(True)
        self.eims_table.setHorizontalHeaderLabels([
            "", "名称", "IP", "端口", "账号", "密码", "计费规则", "状态"
        ])
        header = self.eims_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.eims_table.setColumnWidth(0, 40)

        # 全选 CheckBox（放在表头第0列位置）
        self._select_all_cb = QCheckBox(self.eims_table.horizontalHeader())
        self._select_all_cb.setGeometry(12, 4, 20, 20)
        self._select_all_cb.stateChanged.connect(self._on_select_all_changed)
        # 表头尺寸变化时重新定位全选框
        header.sectionResized.connect(self._reposition_select_all_cb)
        header.geometriesChanged.connect(self._reposition_select_all_cb)

        self.eims_table.setSelectionMode(
            QTableWidget.SelectionMode.ExtendedSelection
        )
        self.eims_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.eims_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.eims_table.itemChanged.connect(self._on_eims_item_changed)
        eims_outer.addWidget(self.eims_table)

        eims_btn_layout = QHBoxLayout()
        eims_btn_layout.setSpacing(6)
        self.eims_add_btn = QPushButton("添加")
        self.eims_add_btn.setProperty("class", "primary")
        self.eims_edit_btn = QPushButton("编辑")
        self.eims_del_btn = QPushButton("删除")
        self.eims_del_btn.setProperty("class", "danger")
        self.eims_test_btn = QPushButton("测试连接")
        self.eims_import_btn = QPushButton("批量导入")
        self.eims_import_btn.setProperty("class", "primary")
        self.eims_batch_del_btn = QPushButton("批量删除")
        self.eims_batch_del_btn.setProperty("class", "danger")
        eims_btn_layout.addWidget(self.eims_add_btn)
        eims_btn_layout.addWidget(self.eims_edit_btn)
        eims_btn_layout.addWidget(self.eims_del_btn)
        eims_btn_layout.addWidget(self.eims_test_btn)
        eims_btn_layout.addWidget(self.eims_import_btn)
        eims_btn_layout.addWidget(self.eims_batch_del_btn)
        eims_outer.addLayout(eims_btn_layout)

        self.eims_add_btn.clicked.connect(self._add_eims)
        self.eims_edit_btn.clicked.connect(self._edit_eims)
        self.eims_del_btn.clicked.connect(self._del_eims)
        self.eims_test_btn.clicked.connect(self._test_eims)
        self.eims_import_btn.clicked.connect(self._batch_import_eims)
        self.eims_batch_del_btn.clicked.connect(self._batch_delete_eims)

        # -- 线路管理区 --
        line_label = QLabel("线路列表（选中上方服务器后显示）")
        line_label.setStyleSheet("font-weight: bold; margin-top: 6px; color: #2563EB; font-size: 13px;")
        eims_outer.addWidget(line_label)

        self.line_table = QTableWidget(0, 4)
        self.line_table.setAlternatingRowColors(True)
        self.line_table.setHorizontalHeaderLabels(["线路名", "区号", "HeroSMS国家", "备注"])
        self.line_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.line_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.line_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.line_table.setMaximumHeight(180)
        eims_outer.addWidget(self.line_table)

        line_btn_layout = QHBoxLayout()
        line_btn_layout.setSpacing(6)
        self.line_add_btn = QPushButton("添加线路")
        self.line_add_btn.setProperty("class", "primary")
        self.line_edit_btn = QPushButton("编辑线路")
        self.line_del_btn = QPushButton("删除线路")
        self.line_del_btn.setProperty("class", "danger")
        self.line_batch_add_btn = QPushButton("批量添加")
        self.line_batch_add_btn.setProperty("class", "primary")
        line_btn_layout.addWidget(self.line_add_btn)
        line_btn_layout.addWidget(self.line_edit_btn)
        line_btn_layout.addWidget(self.line_del_btn)
        line_btn_layout.addWidget(self.line_batch_add_btn)
        eims_outer.addLayout(line_btn_layout)

        self.line_add_btn.clicked.connect(self._add_line)
        self.line_edit_btn.clicked.connect(self._edit_line)
        self.line_del_btn.clicked.connect(self._del_line)
        self.line_batch_add_btn.clicked.connect(self._batch_import_lines)

        # 选中服务器时刷新线路
        self.eims_table.currentCellChanged.connect(self._on_eims_selection_changed)

        # ===== 右栏：HeroSMS 账号 =====
        hero_group = QGroupBox("HeroSMS 账号")
        hero_layout = QFormLayout(hero_group)
        hero_layout.setContentsMargins(12, 20, 12, 12)
        hero_layout.setSpacing(10)

        self.hero_api_key_edit = QLineEdit()
        self.hero_api_key_edit.setPlaceholderText("输入 API Key")
        hero_layout.addRow("API Key:", self.hero_api_key_edit)

        self.hero_balance_label = QLabel("--")
        self.hero_balance_label.setStyleSheet("font-weight: bold; color: #2563EB; font-size: 14px;")
        hero_layout.addRow("余额:", self.hero_balance_label)

        hero_btn_layout = QHBoxLayout()
        hero_btn_layout.setSpacing(8)
        self.hero_balance_btn = QPushButton("查询余额")
        hero_btn_layout.addWidget(self.hero_balance_btn)
        hero_layout.addRow(hero_btn_layout)

        self.hero_balance_btn.clicked.connect(self._query_balance)

        # API Key 输入框自动保存
        self.hero_api_key_edit.textChanged.connect(self._auto_save_hero)

        # 导入导出配置按钮
        config_btn_layout = QHBoxLayout()
        config_btn_layout.setSpacing(8)
        self.export_config_btn = QPushButton("导出配置")
        self.import_config_btn = QPushButton("导入配置")
        config_btn_layout.addWidget(self.export_config_btn)
        config_btn_layout.addWidget(self.import_config_btn)
        hero_layout.addRow(config_btn_layout)

        self.export_config_btn.clicked.connect(self._export_config)
        self.import_config_btn.clicked.connect(self._import_config)

        layout.addWidget(eims_group, stretch=3)
        layout.addWidget(hero_group, stretch=2)

    # ---- 数据加载 ----

    def _load_accounts(self):
        # EIMS 表格
        self._select_all_cb.blockSignals(True)
        self._select_all_cb.setChecked(False)
        self._select_all_cb.blockSignals(False)
        self.eims_table.blockSignals(True)
        self.eims_table.setRowCount(0)
        for srv in self.config.get("eims_servers", []):
            row = self.eims_table.rowCount()
            self.eims_table.insertRow(row)
            # 第0列：勾选框
            cb_item = QTableWidgetItem()
            cb_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            cb_item.setCheckState(Qt.CheckState.Unchecked)
            self.eims_table.setItem(row, 0, cb_item)
            self.eims_table.setItem(row, 1, QTableWidgetItem(srv.get("name", "")))
            self.eims_table.setItem(row, 2, QTableWidgetItem(srv.get("host", "")))
            self.eims_table.setItem(row, 3, QTableWidgetItem(str(srv.get("port", 20003))))
            self.eims_table.setItem(row, 4, QTableWidgetItem(srv.get("username", "")))
            self.eims_table.setItem(row, 5, QTableWidgetItem("****"))
            self.eims_table.setItem(row, 6, QTableWidgetItem(srv.get("charge_rule", "")))
            self.eims_table.setItem(row, 7, QTableWidgetItem("未连接"))
        self.eims_table.blockSignals(False)

        # 清空线路表
        self.line_table.setRowCount(0)

        # HeroSMS API Key（阻塞信号避免加载时触发自动保存）
        hero = self.config.get("herosms", {})
        self.hero_api_key_edit.blockSignals(True)
        self.hero_api_key_edit.setText(hero.get("api_key", ""))
        self.hero_api_key_edit.blockSignals(False)

    def _save_and_reload(self):
        save_config(self.config)
        current_eims_row = self.eims_table.currentRow()
        self._load_accounts()
        if current_eims_row >= 0 and current_eims_row < self.eims_table.rowCount():
            self.eims_table.setCurrentCell(current_eims_row, 0)
        self.config_changed.emit()

    # ---- EIMS 服务器选中 -> 刷新线路 ----

    def _on_eims_selection_changed(self, current_row, _col, _prev_row, _prev_col):
        self._load_lines_for_server(current_row)

    def _load_lines_for_server(self, server_row: int):
        self.line_table.setRowCount(0)
        servers = self.config.get("eims_servers", [])
        if server_row < 0 or server_row >= len(servers):
            return
        for line in servers[server_row].get("lines", []):
            row = self.line_table.rowCount()
            self.line_table.insertRow(row)
            self.line_table.setItem(row, 0, QTableWidgetItem(line.get("country", "")))
            self.line_table.setItem(row, 1, QTableWidgetItem(line.get("country_code", "")))
            self.line_table.setItem(row, 2, QTableWidgetItem(line.get("herosms_country", "")))
            self.line_table.setItem(row, 3, QTableWidgetItem(line.get("remark", "")))

    def _get_selected_server_index(self) -> int:
        """获取当前操作的服务器索引。优先用 currentRow，无效时回退到勾选框（仅勾选1个时）。"""
        servers = self.config.get("eims_servers", [])
        row = self.eims_table.currentRow()
        if 0 <= row < len(servers):
            return row
        # currentRow 无效时，检查勾选框
        checked = []
        for r in range(self.eims_table.rowCount()):
            item = self.eims_table.item(r, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                checked.append(r)
        if len(checked) == 1 and checked[0] < len(servers):
            return checked[0]
        return -1

    # ---- EIMS CRUD ----

    def _add_eims(self):
        dlg = EimsServerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.config.setdefault("eims_servers", []).append(dlg.get_data())
            self._save_and_reload()

    def _edit_eims(self):
        row = self._get_selected_server_index()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选中一个 EIMS 服务器")
            return
        servers = self.config.get("eims_servers", [])
        dlg = EimsServerDialog(self, servers[row])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            servers[row] = dlg.get_data()
            self._save_and_reload()

    def _del_eims(self):
        row = self._get_selected_server_index()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选中一个 EIMS 服务器")
            return
        name = self.config.get("eims_servers", [])[row].get("name", "")
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除 EIMS 服务器「{name}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.config.get("eims_servers", []).pop(row)
        self._save_and_reload()

    def _test_eims(self):
        # 优先测试所有勾选的服务器
        checked = self._get_checked_server_indices()
        if checked:
            for row in checked:
                self.test_eims_requested.emit(row)
            return
        # 没有勾选时，回退到当前选中行
        row = self.eims_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选中或勾选要测试的 EIMS 服务器")
            return
        self.test_eims_requested.emit(row)

    def _batch_import_eims(self):
        """批量导入 EIMS 服务器。"""
        dlg = BatchImportDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        servers = dlg.get_servers()
        if not servers:
            return
        eims_list = self.config.setdefault("eims_servers", [])
        # 检查重复（按 host + username 判断）
        existing = {(s.get("host"), s.get("username")) for s in eims_list}
        # 计算序列号起始值：基于已有服务器数量
        next_seq = len(eims_list) + 1
        added = 0
        skipped = 0
        for srv in servers:
            key = (srv.get("host"), srv.get("username"))
            if key in existing:
                skipped += 1
                continue
            srv["name"] = f"服务器{next_seq:03d}"
            next_seq += 1
            eims_list.append(srv)
            existing.add(key)
            added += 1
        self._save_and_reload()
        msg = f"成功导入 {added} 个服务器"
        if skipped:
            msg += f"，跳过 {skipped} 个重复项"
        QMessageBox.information(self, "导入完成", msg)

    def _batch_delete_eims(self):
        """批量删除勾选的 EIMS 服务器。"""
        checked_rows = []
        for row in range(self.eims_table.rowCount()):
            item = self.eims_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                checked_rows.append(row)
        if not checked_rows:
            QMessageBox.warning(self, "提示", "请先勾选要删除的服务器")
            return
        count = len(checked_rows)
        reply = QMessageBox.question(
            self, "确认批量删除",
            f"确定要删除勾选的 {count} 个服务器吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        servers = self.config.get("eims_servers", [])
        for row in reversed(checked_rows):
            if 0 <= row < len(servers):
                servers.pop(row)
        self._save_and_reload()
        QMessageBox.information(self, "删除完成", f"已删除 {count} 个服务器")

    def update_eims_status(self, row: int, status: str):
        if 0 <= row < self.eims_table.rowCount():
            self.eims_table.setItem(row, 7, QTableWidgetItem(status))

    # ---- 勾选框联动 ----

    def _on_select_all_changed(self, state):
        """全选/取消全选 CheckBox 变化时，同步所有行。"""
        check = Qt.CheckState.Checked if state == Qt.CheckState.Checked.value else Qt.CheckState.Unchecked
        self.eims_table.blockSignals(True)
        for row in range(self.eims_table.rowCount()):
            item = self.eims_table.item(row, 0)
            if item:
                item.setCheckState(check)
        self.eims_table.blockSignals(False)

    def _on_eims_item_changed(self, item):
        """单行勾选变化时，更新全选框状态。"""
        if item.column() != 0:
            return
        total = self.eims_table.rowCount()
        if total == 0:
            return
        checked = sum(
            1 for r in range(total)
            if self.eims_table.item(r, 0) and
            self.eims_table.item(r, 0).checkState() == Qt.CheckState.Checked
        )
        self._select_all_cb.blockSignals(True)
        self._select_all_cb.setChecked(checked == total)
        self._select_all_cb.blockSignals(False)

    def _reposition_select_all_cb(self):
        """重新定位全选 CheckBox 到表头第0列中心。"""
        header = self.eims_table.horizontalHeader()
        x = header.sectionPosition(0) + (header.sectionSize(0) - self._select_all_cb.width()) // 2
        y = (header.height() - self._select_all_cb.height()) // 2
        self._select_all_cb.move(x, y)

    # ---- 线路 CRUD ----

    @staticmethod
    def _extract_server_seq(server_name: str) -> str:
        """从服务器名称中提取数字编号，如 '服务器001' -> '001'。无数字则返回空字符串。"""
        m = re.search(r'\d+', server_name)
        return m.group() if m else ""

    def _add_line(self):
        srv_idx = self._get_selected_server_index()
        if srv_idx < 0:
            QMessageBox.warning(self, "提示", "请先选中一个 EIMS 服务器")
            return
        dlg = LineDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            srv = self.config["eims_servers"][srv_idx]
            data = dlg.get_data()
            seq = self._extract_server_seq(srv.get("name", ""))
            if seq:
                data["country"] = data["country"] + seq
            srv.setdefault("lines", []).append(data)
            save_config(self.config)
            self._load_lines_for_server(srv_idx)
            self.config_changed.emit()

    def _edit_line(self):
        srv_idx = self._get_selected_server_index()
        if srv_idx < 0:
            return
        line_row = self.line_table.currentRow()
        if line_row < 0:
            return
        lines = self.config["eims_servers"][srv_idx].get("lines", [])
        if line_row >= len(lines):
            return
        dlg = LineDialog(self, lines[line_row])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            lines[line_row] = dlg.get_data()
            save_config(self.config)
            self._load_lines_for_server(srv_idx)
            self.config_changed.emit()

    def _del_line(self):
        srv_idx = self._get_selected_server_index()
        if srv_idx < 0:
            return
        line_row = self.line_table.currentRow()
        if line_row < 0:
            return
        lines = self.config["eims_servers"][srv_idx].get("lines", [])
        if line_row >= len(lines):
            return
        line = lines[line_row]
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除线路「{line.get('country', '')}（+{line.get('country_code', '')}）」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        lines.pop(line_row)
        save_config(self.config)
        self._load_lines_for_server(srv_idx)
        self.config_changed.emit()

    def _get_checked_server_indices(self) -> list[int]:
        """获取所有勾选的服务器行索引列表。"""
        checked = []
        servers = self.config.get("eims_servers", [])
        for r in range(self.eims_table.rowCount()):
            item = self.eims_table.item(r, 0)
            if item and item.checkState() == Qt.CheckState.Checked and r < len(servers):
                checked.append(r)
        return checked

    def _batch_import_lines(self):
        """批量添加线路到所有勾选的服务器。"""
        checked_indices = self._get_checked_server_indices()
        if not checked_indices:
            QMessageBox.warning(self, "提示", "请先勾选要添加线路的服务器")
            return
        dlg = BatchImportLineDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_lines = dlg.get_lines()
        if not new_lines:
            return
        servers = self.config.get("eims_servers", [])
        total_added = 0
        total_skipped = 0
        for srv_idx in checked_indices:
            srv = servers[srv_idx]
            seq = self._extract_server_seq(srv.get("name", ""))
            lines_list = srv.setdefault("lines", [])
            existing = {(l.get("country"), l.get("country_code")) for l in lines_list}
            for line in new_lines:
                # 每个服务器独立拷贝，拼接各自的编号
                line_copy = dict(line)
                if seq:
                    line_copy["country"] = line_copy["country"] + seq
                key = (line_copy.get("country"), line_copy.get("country_code"))
                if key in existing:
                    total_skipped += 1
                    continue
                lines_list.append(line_copy)
                existing.add(key)
                total_added += 1
        save_config(self.config)
        # 刷新当前选中服务器的线路显示
        current_row = self.eims_table.currentRow()
        if current_row >= 0:
            self._load_lines_for_server(current_row)
        self.config_changed.emit()
        msg = f"为 {len(checked_indices)} 个服务器添加了共 {total_added} 条线路"
        if total_skipped:
            msg += f"，跳过 {total_skipped} 条重复项"
        QMessageBox.information(self, "添加完成", msg)

    # ---- HeroSMS ----

    def _auto_save_hero(self):
        """API Key 输入框变化时自动保存（静默，不弹窗）。"""
        self.config["herosms"] = {
            "api_key": self.hero_api_key_edit.text().strip(),
            "base_url": self.config.get("herosms", {}).get(
                "base_url", "https://hero-sms.com/stubs/handler_api.php"
            ),
        }
        save_config(self.config)
        self.config_changed.emit()

    def _query_balance(self):
        self.query_balance_requested.emit()

    def update_hero_balance(self, balance: str):
        self.hero_balance_label.setText(balance)

    def update_hero_status(self, status: str):
        self.hero_balance_label.setText(status)

    # ---- 导入导出配置 ----

    def _export_config(self):
        default_name = f"config_backup_{date.today().strftime('%Y%m%d')}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", default_name, "JSON 文件 (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "导出成功", f"配置已导出到:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"写入文件时出错:\n{e}")

    def _import_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入配置", "", "JSON 文件 (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"读取或解析文件时出错:\n{e}")
            return
        if not isinstance(data, dict) or "herosms" not in data or "eims_servers" not in data:
            QMessageBox.warning(
                self, "格式错误",
                "配置文件不合法: 缺少 herosms 或 eims_servers 字段"
            )
            return
        reply = QMessageBox.question(
            self, "确认导入",
            "导入将覆盖当前所有配置，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.config.clear()
        self.config.update(data)
        save_config(self.config)
        self._load_accounts()
        self.config_changed.emit()
        QMessageBox.information(self, "导入成功", "配置已导入并生效")
