"""落地检测核心引擎。

编排完整检测流程：
  一次性获取所有运营商号码 → 所有服务器×运营商并行发送 → 统一轮询收信 → 矩阵式结果。
使用 QThread + Worker(QObject) 模式，不阻塞 GUI。
"""

import logging
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QTimer

from api.eims_client import (
    EIMSClient, get_status_message, get_send_status_message,
    get_deliver_status_message,
)
from api.herosms_client import HeroSMSClient, HeroSMSError

# 号码缓存有效期（秒）
PHONE_CACHE_TTL = 20 * 60  # 20 分钟

logger = logging.getLogger(__name__)


class DetectionWorker(QObject):
    """在子线程中执行检测任务，通过信号通知 GUI。

    信号:
        cell_update(dict)       — 更新矩阵表格中的单个单元格
        status_update(str)      — 状态/日志文字
        detection_finished()    — 全部检测完成
        error_occurred(str)     — 错误信息
    """

    cell_update = Signal(dict)
    status_update = Signal(str)
    detection_finished = Signal()
    error_occurred = Signal(str)

    def __init__(self, eims_clients: list[tuple[str, EIMSClient]],
                 herosms_client: HeroSMSClient, params: dict,
                 phone_cache: dict | None = None):
        super().__init__()
        self._eims_clients = eims_clients
        self._herosms = herosms_client
        self._params = params
        self._stopped = False
        self._finished_emitted = False
        # phone_cache: {operator_name: {"phone": str, "activation_id": int, "time": float}}
        self._phone_cache = phone_cache if phone_cache is not None else {}

        # 暴露给 Engine 的数据（run 完成后可读取）
        self.op_info: dict = {}
        self.uuid_map: dict = {}
        self.send_map: dict = {}
        self.used_cache_ops: set = set()  # 记录哪些运营商使用了缓存号码

    def stop(self):
        self._stopped = True

    def _emit_finished(self):
        """安全发射 detection_finished 信号，防止重复发射。"""
        if not self._finished_emitted:
            self._finished_emitted = True
            self.detection_finished.emit()

    def _emit_cell(self, srv_idx: int, op_idx: int, field: str, value: str):
        """发送单元格更新信号。

        field: "send" | "deliver" | "landed" | "reason" | "phone" | "elapsed"
        """
        logger.debug("emit: %s,%s,%s,%s", srv_idx, op_idx, field, value[:20] if isinstance(value, str) else value)
        self.cell_update.emit({
            "srv_idx": srv_idx, "op_idx": op_idx,
            "field": field, "value": value,
        })

    @Slot()
    def run(self):
        """主流程：批量取号 → 并行发送 → 轮询EIMS → 统一轮询HeroSMS → 标记结果。"""
        logger.debug("worker.run 开始执行")
        try:
            operators = self._params.get("operators", []) or ["any"]
            service = self._params.get("service", "")
            country = self._params.get("country", 0)
            content = self._params.get("content", "test")
            timeout = self._params.get("timeout", 120)
            interval = self._params.get("check_interval", 5)
            start_time = time.time()

            def elapsed():
                return f"{time.time() - start_time:.1f}s"

            num_srv = len(self._eims_clients)
            num_op = len(operators)

            # ===== 步骤1: 批量获取所有运营商号码（优先使用缓存） =====
            self.status_update.emit(f"正在获取 {num_op} 个运营商的号码...")
            logger.debug("开始取号, 运营商数=%s, 服务器数=%s", num_op, num_srv)

            # op_info: {op_idx: {"phone": str, "activation_id": int, "op_name": str}}
            op_info = {}
            self.op_info = op_info
            now = time.time()
            for op_idx, op in enumerate(operators):
                if self._stopped:
                    break
                op_name = op if op != "any" else "any"

                # 先查缓存
                cached = self._phone_cache.get(op_name)
                if cached and (now - cached["time"]) < PHONE_CACHE_TTL:
                    phone = cached["phone"]
                    aid = cached["activation_id"]
                    op_info[op_idx] = {"phone": phone, "activation_id": aid, "op_name": op_name}
                    self.used_cache_ops.add(op_name)
                    self.status_update.emit(
                        f"[{op_name}] 复用缓存号码: {phone} (ID={aid})")
                    for si in range(num_srv):
                        self._emit_cell(si, op_idx, "phone", phone)
                    continue

                try:
                    kwargs = {"service": service, "country": country}
                    if op != "any":
                        kwargs["operator"] = op
                    info = self._herosms.get_number(**kwargs)
                    aid = int(info.get("activationId", 0))
                    phone = str(info.get("phoneNumber", ""))
                    op_info[op_idx] = {"phone": phone, "activation_id": aid, "op_name": op_name}
                    # 写入缓存
                    self._phone_cache[op_name] = {
                        "phone": phone, "activation_id": aid, "time": time.time(),
                    }
                    self.status_update.emit(
                        f"[{op_name}] 取号成功: {phone} (ID={aid})")
                    # 向所有服务器行发送号码
                    for si in range(num_srv):
                        self._emit_cell(si, op_idx, "phone", phone)
                except Exception as e:
                    self.status_update.emit(f"[{op_name}] 取号失败: {e}")
                    self.error_occurred.emit(f"[{op_name}] 取号失败: {e}")
                    op_info[op_idx] = {"phone": "", "activation_id": 0, "op_name": op_name, "failed": True}
                    for si in range(num_srv):
                        self._emit_cell(si, op_idx, "send", "取号失败")
                        self._emit_cell(si, op_idx, "landed", "取号失败")
                        self._emit_cell(si, op_idx, "reason", str(e))

            if self._stopped:
                self._cleanup_all(op_info)
                self._emit_finished()
                return

            # ===== 步骤2: 并行发送 + 轮询EIMS（每个 srv×op 一个线程） =====
            logger.debug("取号完成，开始发送短信, 成功取号=%s/%s",
                         len([o for o in op_info.values() if not o.get('failed')]), len(op_info))
            send_map = {}  # (srv_idx, op_idx) -> {"send_id": int, "ok": bool, "tag": str}
            uuid_map = {}  # tag -> (srv_idx, op_idx)
            self.send_map = send_map
            self.uuid_map = uuid_map

            def _send_and_poll_eims(si, op_idx, srv_name, eims_client, phone, tag, op_name):
                """单个 (srv, op) 的完整流程：发送 → 轮询 EIMS 报告。"""
                print(f"[DEBUG] 正在发送: 服务器{si}/{op_name}, tag={tag}")
                tagged = f"{content} {tag}"
                # 发送
                try:
                    resp = eims_client.send_sms(numbers=phone, content=tagged)
                except Exception as exc:
                    return si, op_idx, tag, "send_error", str(exc), None
                api_status = resp.get("status", -99)
                if api_status != 0:
                    msg = get_status_message(api_status)
                    return si, op_idx, tag, "send_fail", msg, None
                arr = resp.get("array", [])
                sid = int(arr[0][1]) if arr and len(arr[0]) >= 2 else 0
                # 轮询 EIMS 报告
                ok, deliver_msg, fail = self._poll_eims_report(eims_client, sid, srv_name)
                if ok:
                    return si, op_idx, tag, "ok", deliver_msg, sid
                else:
                    return si, op_idx, tag, "eims_fail", fail, sid

            # 构建任务列表
            tasks = []
            for op_idx, oi in op_info.items():
                if oi.get("failed"):
                    continue
                phone = oi["phone"]
                op_name = oi["op_name"]
                for si, (srv_name, eims_client) in enumerate(self._eims_clients):
                    tag = uuid.uuid4().hex[:8]
                    uuid_map[tag] = (si, op_idx)
                    tasks.append((si, op_idx, srv_name, eims_client, phone, tag, op_name))
                    self._emit_cell(si, op_idx, "send", "准备发送")

            self.status_update.emit(f"并行处理 {len(tasks)} 个发送任务...")

            with ThreadPoolExecutor(max_workers=min(len(tasks), 20) if tasks else 1) as pool:
                futures = {
                    pool.submit(_send_and_poll_eims, *t): t for t in tasks
                }
                for fut in as_completed(futures):
                    si, op_idx, tag, status, msg, sid = fut.result()
                    srv_name = self._eims_clients[si][0]
                    op_name = op_info[op_idx]["op_name"]
                    if status == "send_error":
                        send_map[(si, op_idx)] = {"send_id": 0, "ok": False, "tag": tag}
                        self._emit_cell(si, op_idx, "send", "提交异常")
                        self._emit_cell(si, op_idx, "landed", "发送失败")
                        self._emit_cell(si, op_idx, "reason", msg)
                        self.status_update.emit(f"[{srv_name}/{op_name}] 提交异常: {msg}")
                    elif status == "send_fail":
                        send_map[(si, op_idx)] = {"send_id": 0, "ok": False, "tag": tag}
                        self._emit_cell(si, op_idx, "send", f"失败:{msg}")
                        self._emit_cell(si, op_idx, "landed", "发送失败")
                        self._emit_cell(si, op_idx, "reason", msg)
                        self.status_update.emit(f"[{srv_name}/{op_name}] 提交失败: {msg}")
                    elif status == "eims_fail":
                        send_map[(si, op_idx)] = {"send_id": sid or 0, "ok": False, "tag": tag}
                        self._emit_cell(si, op_idx, "send", "发送失败")
                        self._emit_cell(si, op_idx, "deliver", msg or "失败")
                        self._emit_cell(si, op_idx, "landed", "发送失败")
                        self._emit_cell(si, op_idx, "reason", msg)
                        self.status_update.emit(f"[{srv_name}/{op_name}] EIMS失败: {msg}")
                    else:  # ok
                        send_map[(si, op_idx)] = {"send_id": sid or 0, "ok": True, "tag": tag}
                        self._emit_cell(si, op_idx, "send", "已发送")
                        self._emit_cell(si, op_idx, "deliver", msg or "已送达")
                        self.status_update.emit(f"[{srv_name}/{op_name}] 发送成功")

            if self._stopped:
                self._cleanup_all(op_info)
                self._emit_finished()
                return

            # ===== 步骤3: 统一轮询所有activation_id的HeroSMS收信 =====
            # 构建等待集合: {(srv_idx, op_idx)} 和 activation_id 列表
            waiting = set()
            active_ops = {}  # op_idx -> activation_id
            for (si, oi), info in send_map.items():
                if info["ok"]:
                    waiting.add((si, oi))
                    if oi not in active_ops and op_info[oi].get("activation_id"):
                        active_ops[oi] = op_info[oi]["activation_id"]
                    self._emit_cell(si, oi, "landed", f"检测中({elapsed()})")

            if not waiting:
                self.status_update.emit("所有发送均失败，跳过收信轮询")
                self._cleanup_all(op_info)
                self._emit_finished()
                return

            # 从当前时刻重新计算截止时间，而非从 start_time 算起
            # 因为步骤1(取号)和步骤2(并行发送+EIMS轮询)已消耗大量时间
            hero_timeout = max(timeout, 60)  # 至少给60秒轮询HeroSMS
            self.status_update.emit(
                f"开始轮询收信 (超时={hero_timeout}秒, 间隔={interval}秒, "
                f"已用时{elapsed()})...")
            deadline = time.time() + hero_timeout
            landed = {}  # (srv_idx, op_idx) -> sms_text
            poll_count = 0

            while time.time() < deadline and not self._stopped and waiting:
                poll_count += 1
                for oi, aid in list(active_ops.items()):
                    if self._stopped:
                        break
                    try:
                        sms_list = self._herosms.get_all_sms(aid)
                    except Exception as e:
                        self.status_update.emit(f"轮询异常 (op={operators[oi]}): {e}")
                        continue

                    texts = self._extract_all_sms_texts(sms_list)

                    if poll_count <= 3 or texts:
                        self.status_update.emit(
                            f"[轮询#{poll_count}] aid={aid} "
                            f"getAllSms返回 {len(sms_list)} 条, "
                            f"提取到 {len(texts)} 条文本: {texts[:3]}")

                    if texts:
                        for text in texts:
                            for tag, (si, tag_oi) in uuid_map.items():
                                if (si, tag_oi) in waiting and tag in text:
                                    landed[(si, tag_oi)] = text
                                    waiting.discard((si, tag_oi))
                                    srv_name = self._eims_clients[si][0]
                                    self._emit_cell(si, tag_oi, "landed", f"已落地({elapsed()})")
                                    self._emit_cell(si, tag_oi, "elapsed", elapsed())
                                    self.status_update.emit(f"[{srv_name}/{operators[tag_oi]}] 收到短信")

                if not waiting:
                    break
                for si, oi in list(waiting):
                    self._emit_cell(si, oi, "landed", f"检测中({elapsed()})")
                self._interruptible_sleep(interval)

            # ===== 步骤4: 标记最终结果 =====
            for (si, oi), info in send_map.items():
                if not info["ok"]:
                    continue
                if (si, oi) in landed:
                    self._emit_cell(si, oi, "landed", f"已落地({elapsed()})")
                    self._emit_cell(si, oi, "elapsed", elapsed())
                elif self._stopped:
                    self._emit_cell(si, oi, "landed", "已停止")
                    self._emit_cell(si, oi, "reason", "用户停止")
                    self._emit_cell(si, oi, "elapsed", elapsed())
                else:
                    self._emit_cell(si, oi, "landed", f"未落地({elapsed()})")
                    self._emit_cell(si, oi, "reason", "超时未收到")
                    self._emit_cell(si, oi, "elapsed", elapsed())

            self._cleanup_all(op_info)

        except Exception as e:
            traceback.print_exc()
            logger.exception("检测流程异常")
            self.error_occurred.emit(f"检测异常: {e}")
        finally:
            self._emit_finished()

    @staticmethod
    def _extract_sms_texts(sd: dict) -> list[str]:
        """从 getStatusV2 响应中提取所有短信文本。

        兼容多种响应格式:
        - sms 为 dict: {"text": "...", "code": "..."}
        - sms 为 list: [{"text": "...", "code": "..."}, ...]
        - sms 为 str: 直接作为短信文本
        - sms 为 None / 空字符串 / 其他
        - 同时检查 full_text 和 code 字段作为后备
        """
        sms_data = sd.get("sms")
        texts = []
        if isinstance(sms_data, str) and sms_data:
            texts.append(sms_data)
        elif isinstance(sms_data, dict):
            for key in ("text", "full_text", "code"):
                t = sms_data.get(key, "")
                if t and t not in texts:
                    texts.append(t)
        elif isinstance(sms_data, list):
            for item in sms_data:
                if isinstance(item, dict):
                    for key in ("text", "full_text", "code"):
                        t = item.get(key, "")
                        if t and t not in texts:
                            texts.append(t)
                elif isinstance(item, str) and item:
                    if item not in texts:
                        texts.append(item)
        return texts

    @staticmethod
    def _extract_all_sms_texts(sms_list: list) -> list[str]:
        """从 getAllSms 返回的 data 数组中提取所有短信文本。

        每个元素可能包含 text, full_text, code 等字段。
        """
        texts = []
        for item in sms_list:
            if isinstance(item, dict):
                for key in ("text", "full_text", "code"):
                    t = item.get(key, "")
                    if t and t not in texts:
                        texts.append(t)
            elif isinstance(item, str) and item:
                if item not in texts:
                    texts.append(item)
        return texts

    def _cleanup_all(self, op_info: dict):
        """清理所有 activation_id（跳过缓存复用的号码）。"""
        for oi, info in op_info.items():
            aid = info.get("activation_id", 0)
            op_name = info.get("op_name", "")
            if aid and op_name not in self.used_cache_ops:
                self._cleanup(aid, cancel=True)

    def _poll_eims_report(
        self, eims_client: EIMSClient, send_id: int, server_name: str = "",
    ) -> tuple[bool, str, str]:
        """轮询 EIMS get_report 直到发送状态确定。"""
        report_timeout = 30
        report_interval = 3
        deadline = time.time() + report_timeout
        self._interruptible_sleep(2)
        while time.time() < deadline and not self._stopped:
            try:
                report = eims_client.get_report([send_id])
                arr = report.get("array", [])
                if not arr or len(arr[0]) < 4:
                    self._interruptible_sleep(report_interval)
                    continue
                send_status = arr[0][3]
                send_msg = get_send_status_message(send_status)
                deliver_status = arr[0][5] if len(arr[0]) >= 6 else 0
                deliver_msg = get_deliver_status_message(deliver_status)
                if send_status == 0:
                    return True, deliver_msg, ""
                elif send_status in (1, 2):
                    self._interruptible_sleep(report_interval)
                    continue
                else:
                    return False, deliver_msg, send_msg
            except Exception as e:
                logger.warning("[%s] 报告查询异常: %s", server_name, e)
                self._interruptible_sleep(report_interval)
        if self._stopped:
            return False, "", "用户停止"
        return False, "", "报告查询超时"

    def _cleanup(self, activation_id, cancel: bool):
        try:
            activation_id = int(activation_id)
        except (TypeError, ValueError):
            return
        if activation_id <= 0:
            return
        try:
            if cancel:
                self._herosms.cancel_activation(activation_id)
                self.status_update.emit(f"已取消激活 (ID={activation_id})")
            else:
                self._herosms.finish_activation(activation_id)
                self.status_update.emit(f"已完成激活 (ID={activation_id})")
        except HeroSMSError as e:
            # 激活已取消/已完成/不存在等业务错误，静默处理
            logger.debug("清理激活 ID=%s 业务错误: %s", activation_id, e)
        except Exception as e:
            self.status_update.emit(f"清理激活失败 (ID={activation_id}): {e}")

    def _interruptible_sleep(self, seconds: float):
        end = time.time() + seconds
        while time.time() < end and not self._stopped:
            time.sleep(min(0.5, end - time.time()))


class RetestWorker(QObject):
    """重新测试：复用上一轮号码，只重新发送+轮询未落地的服务器。"""

    cell_update = Signal(dict)
    status_update = Signal(str)
    detection_finished = Signal()
    error_occurred = Signal(str)

    def __init__(self, eims_clients: list[tuple[str, EIMSClient]],
                 herosms_client: HeroSMSClient, params: dict,
                 prev_op_info: dict, failed_pairs: list[tuple[int, int]]):
        super().__init__()
        self._eims_clients = eims_clients
        self._herosms = herosms_client
        self._params = params
        self._prev_op_info = prev_op_info
        self._failed_pairs = failed_pairs
        self._stopped = False
        self._finished_emitted = False
        self.op_info = dict(prev_op_info)
        self.uuid_map: dict = {}
        self.send_map: dict = {}

    def stop(self):
        self._stopped = True

    def _emit_finished(self):
        """安全发射 detection_finished 信号，防止重复发射。"""
        if not self._finished_emitted:
            self._finished_emitted = True
            self.detection_finished.emit()

    def _emit_cell(self, srv_idx: int, op_idx: int, field: str, value: str):
        self.cell_update.emit({
            "srv_idx": srv_idx, "op_idx": op_idx,
            "field": field, "value": value,
        })

    def _interruptible_sleep(self, seconds: float):
        end = time.time() + seconds
        while time.time() < end and not self._stopped:
            time.sleep(min(0.5, end - time.time()))

    def _poll_eims_report(self, eims_client, send_id, server_name=""):
        report_timeout = 30
        report_interval = 3
        deadline = time.time() + report_timeout
        self._interruptible_sleep(2)
        while time.time() < deadline and not self._stopped:
            try:
                report = eims_client.get_report([send_id])
                arr = report.get("array", [])
                if not arr or len(arr[0]) < 4:
                    self._interruptible_sleep(report_interval)
                    continue
                send_status = arr[0][3]
                send_msg = get_send_status_message(send_status)
                deliver_status = arr[0][5] if len(arr[0]) >= 6 else 0
                deliver_msg = get_deliver_status_message(deliver_status)
                if send_status == 0:
                    return True, deliver_msg, ""
                elif send_status in (1, 2):
                    self._interruptible_sleep(report_interval)
                    continue
                else:
                    return False, deliver_msg, send_msg
            except Exception as e:
                logger.warning("[%s] 报告查询异常: %s", server_name, e)
                self._interruptible_sleep(report_interval)
        if self._stopped:
            return False, "", "用户停止"
        return False, "", "报告查询超时"

    @Slot()
    def run(self):
        try:
            operators = self._params.get("operators", []) or ["any"]
            content = self._params.get("content", "test")
            timeout = self._params.get("timeout", 120)
            interval = self._params.get("check_interval", 5)
            start_time = time.time()

            def elapsed():
                return f"{time.time() - start_time:.1f}s"

            send_map = {}
            uuid_map = {}
            self.send_map = send_map
            self.uuid_map = uuid_map

            tasks = []
            for si, op_idx in self._failed_pairs:
                oi = self._prev_op_info.get(op_idx)
                if not oi or oi.get("failed") or not oi.get("phone"):
                    continue
                phone = oi["phone"]
                op_name = oi["op_name"]
                if si >= len(self._eims_clients):
                    continue
                srv_name, eims_client = self._eims_clients[si]
                tag = uuid.uuid4().hex[:8]
                uuid_map[tag] = (si, op_idx)
                tasks.append((si, op_idx, srv_name, eims_client, phone, tag, op_name))
                self._emit_cell(si, op_idx, "send", "准备重发")
                self._emit_cell(si, op_idx, "landed", "重测中...")
                self._emit_cell(si, op_idx, "reason", "")
                self._emit_cell(si, op_idx, "phone", phone)

            if not tasks:
                self.status_update.emit("没有需要重新测试的项目")
                self._emit_finished()
                return

            self.status_update.emit(f"重新测试 {len(tasks)} 个未落地项...")

            def _send_and_poll(si, op_idx, srv_name, eims_client, phone, tag, _op_name):
                tagged = f"{content} {tag}"
                try:
                    resp = eims_client.send_sms(numbers=phone, content=tagged)
                except Exception as exc:
                    return si, op_idx, tag, "send_error", str(exc), None
                api_status = resp.get("status", -99)
                if api_status != 0:
                    return si, op_idx, tag, "send_fail", get_status_message(api_status), None
                arr = resp.get("array", [])
                sid = int(arr[0][1]) if arr and len(arr[0]) >= 2 else 0
                ok, deliver_msg, fail = self._poll_eims_report(eims_client, sid, srv_name)
                if ok:
                    return si, op_idx, tag, "ok", deliver_msg, sid
                return si, op_idx, tag, "eims_fail", fail, sid

            with ThreadPoolExecutor(max_workers=min(len(tasks), 20)) as pool:
                futures = {pool.submit(_send_and_poll, *t): t for t in tasks}
                for fut in as_completed(futures):
                    si, op_idx, tag, status, msg, sid = fut.result()
                    srv_name = self._eims_clients[si][0]
                    if status in ("send_error", "send_fail", "eims_fail"):
                        send_map[(si, op_idx)] = {"send_id": sid or 0, "ok": False, "tag": tag}
                        self._emit_cell(si, op_idx, "send", "发送失败")
                        self._emit_cell(si, op_idx, "landed", "发送失败")
                        self._emit_cell(si, op_idx, "reason", msg)
                    else:
                        send_map[(si, op_idx)] = {"send_id": sid or 0, "ok": True, "tag": tag}
                        self._emit_cell(si, op_idx, "send", "已发送")
                        self._emit_cell(si, op_idx, "deliver", msg or "已送达")

            if self._stopped:
                self._emit_finished()
                return

            waiting = set()
            active_ops = {}
            for (si, oi), info in send_map.items():
                if info["ok"]:
                    waiting.add((si, oi))
                    if oi not in active_ops and self._prev_op_info.get(oi, {}).get("activation_id"):
                        active_ops[oi] = self._prev_op_info[oi]["activation_id"]
                    self._emit_cell(si, oi, "landed", f"检测中({elapsed()})")

            if not waiting:
                self.status_update.emit("所有重发均失败")
                self._emit_finished()
                return

            hero_timeout = max(timeout, 60)
            deadline = time.time() + hero_timeout
            landed = {}
            poll_count = 0

            while time.time() < deadline and not self._stopped and waiting:
                poll_count += 1
                for oi, aid in list(active_ops.items()):
                    if self._stopped:
                        break
                    try:
                        sms_list = self._herosms.get_all_sms(aid)
                    except Exception as e:
                        self.status_update.emit(f"轮询异常 (op={operators[oi]}): {e}")
                        continue
                    texts = DetectionWorker._extract_all_sms_texts(sms_list)
                    if poll_count <= 3 or texts:
                        self.status_update.emit(
                            f"[重测轮询#{poll_count}] aid={aid} "
                            f"getAllSms返回 {len(sms_list)} 条, "
                            f"提取到 {len(texts)} 条文本: {texts[:3]}")
                    if texts:
                        for text in texts:
                            for tag, (si, tag_oi) in uuid_map.items():
                                if (si, tag_oi) in waiting and tag in text:
                                    landed[(si, tag_oi)] = text
                                    waiting.discard((si, tag_oi))
                                    srv_name = self._eims_clients[si][0]
                                    self._emit_cell(si, tag_oi, "landed", f"已落地({elapsed()})")
                                    self._emit_cell(si, tag_oi, "elapsed", elapsed())
                                    self.status_update.emit(
                                        f"[重测] [{srv_name}/{operators[tag_oi]}] 收到短信")
                if not waiting:
                    break
                for si, oi in list(waiting):
                    self._emit_cell(si, oi, "landed", f"检测中({elapsed()})")
                self._interruptible_sleep(interval)

            for (si, oi), info in send_map.items():
                if not info["ok"]:
                    continue
                if (si, oi) in landed:
                    self._emit_cell(si, oi, "landed", f"已落地({elapsed()})")
                    self._emit_cell(si, oi, "elapsed", elapsed())
                elif self._stopped:
                    self._emit_cell(si, oi, "landed", "已停止")
                    self._emit_cell(si, oi, "elapsed", elapsed())
                else:
                    self._emit_cell(si, oi, "landed", f"未落地({elapsed()})")
                    self._emit_cell(si, oi, "reason", "超时未收到")
                    self._emit_cell(si, oi, "elapsed", elapsed())

        except Exception as e:
            logger.exception("重测流程异常")
            self.error_occurred.emit(f"重测异常: {e}")
        finally:
            self._emit_finished()


class RecheckWorker(QObject):
    """落地查询：不发短信，只用上一轮 UUID 和 activation_id 重新轮询 HeroSMS。"""

    cell_update = Signal(dict)
    status_update = Signal(str)
    detection_finished = Signal()
    error_occurred = Signal(str)

    def __init__(self, herosms_client: HeroSMSClient, params: dict,
                 prev_op_info: dict, prev_uuid_map: dict,
                 prev_send_map: dict, eims_names: list[str]):
        super().__init__()
        self._herosms = herosms_client
        self._params = params
        self._prev_op_info = prev_op_info
        self._prev_uuid_map = prev_uuid_map
        self._prev_send_map = prev_send_map
        self._eims_names = eims_names
        self._stopped = False
        self._finished_emitted = False

    def stop(self):
        self._stopped = True

    def _emit_finished(self):
        """安全发射 detection_finished 信号，防止重复发射。"""
        if not self._finished_emitted:
            self._finished_emitted = True
            self.detection_finished.emit()

    def _emit_cell(self, srv_idx: int, op_idx: int, field: str, value: str):
        self.cell_update.emit({
            "srv_idx": srv_idx, "op_idx": op_idx,
            "field": field, "value": value,
        })

    def _interruptible_sleep(self, seconds: float):
        end = time.time() + seconds
        while time.time() < end and not self._stopped:
            time.sleep(min(0.5, end - time.time()))

    @Slot()
    def run(self):
        try:
            operators = self._params.get("operators", []) or ["any"]
            timeout = self._params.get("timeout", 120)
            interval = self._params.get("check_interval", 5)
            start_time = time.time()

            def elapsed():
                return f"{time.time() - start_time:.1f}s"

            waiting = set()
            active_ops = {}
            for (si, oi), info in self._prev_send_map.items():
                if info.get("ok"):
                    waiting.add((si, oi))
                    if oi not in active_ops and self._prev_op_info.get(oi, {}).get("activation_id"):
                        active_ops[oi] = self._prev_op_info[oi]["activation_id"]
                    self._emit_cell(si, oi, "landed", f"查询中({elapsed()})")
                    # 发送号码到表格
                    phone = self._prev_op_info.get(oi, {}).get("phone", "")
                    if phone:
                        self._emit_cell(si, oi, "phone", phone)

            if not waiting:
                self.status_update.emit("没有可查询的项目")
                self._emit_finished()
                return

            self.status_update.emit(
                f"开始落地查询 ({len(waiting)} 项, 超时={timeout}秒)...")
            hero_timeout = max(timeout, 60)
            deadline = time.time() + hero_timeout
            landed = {}
            poll_count = 0

            while time.time() < deadline and not self._stopped and waiting:
                poll_count += 1
                for oi, aid in list(active_ops.items()):
                    if self._stopped:
                        break
                    try:
                        sms_list = self._herosms.get_all_sms(aid)
                    except Exception as e:
                        self.status_update.emit(f"查询异常 (op={operators[oi]}): {e}")
                        continue
                    texts = DetectionWorker._extract_all_sms_texts(sms_list)
                    if poll_count <= 3 or texts:
                        self.status_update.emit(
                            f"[查询#{poll_count}] aid={aid} "
                            f"getAllSms返回 {len(sms_list)} 条, "
                            f"提取到 {len(texts)} 条文本: {texts[:3]}")
                    if texts:
                        for text in texts:
                            for tag, (si, tag_oi) in self._prev_uuid_map.items():
                                if (si, tag_oi) in waiting and tag in text:
                                    landed[(si, tag_oi)] = text
                                    waiting.discard((si, tag_oi))
                                    srv_name = self._eims_names[si] if si < len(self._eims_names) else f"服务器{si}"
                                    self._emit_cell(si, tag_oi, "landed", f"已落地({elapsed()})")
                                    self._emit_cell(si, tag_oi, "elapsed", elapsed())
                                    self.status_update.emit(
                                        f"[查询] [{srv_name}/{operators[tag_oi]}] 已落地")
                if not waiting:
                    break
                for si, oi in list(waiting):
                    self._emit_cell(si, oi, "landed", f"查询中({elapsed()})")
                self._interruptible_sleep(interval)

            for (si, oi), info in self._prev_send_map.items():
                if not info.get("ok"):
                    continue
                if (si, oi) in landed:
                    self._emit_cell(si, oi, "landed", f"已落地({elapsed()})")
                    self._emit_cell(si, oi, "elapsed", elapsed())
                elif self._stopped:
                    self._emit_cell(si, oi, "landed", "已停止")
                    self._emit_cell(si, oi, "elapsed", elapsed())
                else:
                    self._emit_cell(si, oi, "landed", f"未落地({elapsed()})")
                    self._emit_cell(si, oi, "elapsed", elapsed())

        except Exception as e:
            logger.exception("落地查询异常")
            self.error_occurred.emit(f"查询异常: {e}")
        finally:
            self._emit_finished()


class DetectionEngine(QObject):
    """管理检测线程生命周期，连接 Worker 信号到 GUI。

    继承 QObject 以确保 QueuedConnection 信号能正确投递到主线程事件循环。
    """

    # 号码缓存变更信号，通知 GUI 刷新活跃号码列表
    phone_cache_changed = Signal(list)  # list of {"operator": str, "phone": str, "activation_id": int, "time": float}

    def __init__(self, main_window):
        super().__init__(main_window)
        self._mw = main_window
        self._thread: QThread | None = None
        self._worker = None
        self._dead_threads: list[tuple[QThread, QObject]] = []  # 已完成待清理

        # HeroSMS 活跃号码缓存: {operator_name: {"phone": str, "activation_id": int, "time": float}}
        self._phone_cache: dict = {}

        # 上一轮检测数据，供重新测试/落地查询复用
        self._last_op_info: dict = {}
        self._last_uuid_map: dict = {}
        self._last_send_map: dict = {}
        self._last_params: dict = {}
        self._last_eims_clients: list = []
        self._last_operators: list = []
        self._last_herosms: HeroSMSClient | None = None

        tab = self._mw.detection_tab
        tab.start_requested.connect(self.start_detection)
        tab.stop_requested.connect(self.stop_detection)
        tab.retest_requested.connect(self.start_retest)
        tab.recheck_requested.connect(self.start_recheck)
        tab.clear_cache_btn.clicked.connect(self.clear_phone_cache)
        self.phone_cache_changed.connect(tab.update_phone_cache_display)

    def start_detection(self, params: dict):
        logger.info("start_detection 被调用, params=%s", list(params.keys()) if params else None)
        if self._thread and self._thread.isRunning():
            logger.warning("跳过：线程仍在运行")
            self._on_status("检测正在进行中，请等待完成")
            return

        # 启动前清理旧线程
        self._cleanup_dead_threads()

        tab = self._mw.detection_tab
        config = self._mw.config

        # 构建 EIMS 客户端列表
        servers = config.get("eims_servers", [])
        selected_indices = params.get("eims_servers", [])
        target_country = params.get("country", "").lower()
        eims_clients: list[tuple[str, EIMSClient]] = []
        server_names: list[str] = []
        for idx in selected_indices:
            if idx < 0 or idx >= len(servers):
                continue
            srv = servers[idx]
            # 优先使用匹配当前国家的线路名作为显示名
            name = srv.get("name", f"服务器{idx+1}")
            for line in srv.get("lines", []):
                if target_country and line.get("herosms_country", "").lower() == target_country:
                    name = line.get("country", "") or name
                    break
            client = EIMSClient(
                host=srv.get("host", ""),
                port=int(srv.get("port", 20003)),
                account=srv.get("username", ""),
                password=srv.get("password", ""),
                use_md5=srv.get("md5_auth", False),
                protocol_key=srv.get("protocol_key", ""),
            )
            eims_clients.append((name, client))
            server_names.append(name)

        if not eims_clients:
            tab.progress_label.setText("无可用线路")
            tab.set_running(False)
            return

        # HeroSMS 客户端
        hero = config.get("herosms", {})
        herosms_client = HeroSMSClient(
            api_key=hero.get("api_key", ""),
            base_url=hero.get(
                "base_url", "https://hero-sms.com/stubs/handler_api.php"),
            timeout=15,
        )

        # 运营商列表
        operators = params.get("operators", []) or ["any"]

        # 设置矩阵表格
        tab.setup_result_table(server_names, operators)
        tab.set_running(True)

        # 补充参数
        params["operators"] = operators
        params["country"] = params.get("hero_country_id", 0)

        # 保存本轮数据供 retest/recheck 复用
        self._last_eims_clients = eims_clients
        self._last_herosms = herosms_client
        self._last_operators = operators
        self._last_params = dict(params)

        # 清理过期缓存
        self._purge_expired_cache()

        # 创建 Worker + Thread（传入号码缓存）
        self._thread = QThread()
        self._worker = DetectionWorker(eims_clients, herosms_client, params, self._phone_cache)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.cell_update.connect(self._on_cell_update, Qt.ConnectionType.QueuedConnection)
        self._worker.status_update.connect(self._on_status, Qt.ConnectionType.QueuedConnection)
        self._worker.error_occurred.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
        self._worker.detection_finished.connect(self._on_finished, Qt.ConnectionType.QueuedConnection)

        self._thread.start()

    def stop_detection(self):
        if self._worker:
            self._worker.stop()

    @Slot(dict)
    def _on_cell_update(self, data: dict):
        tab = self._mw.detection_tab
        tab.update_cell(
            data["srv_idx"], data["op_idx"],
            data["field"], data["value"],
        )

    @Slot(str)
    def _on_status(self, msg: str):
        self._mw.status_bar.showMessage(msg)
        if hasattr(self._mw, "log_tab"):
            self._mw.log_tab.append_log(msg)

    @Slot(str)
    def _on_error(self, msg: str):
        self._mw.status_bar.showMessage(f"错误: {msg}")
        if hasattr(self._mw, "log_tab"):
            self._mw.log_tab.append_log(f"[错误] {msg}")

    @Slot()
    def _on_finished(self):
        # 从 DetectionWorker 提取上一轮数据（RetestWorker/RecheckWorker 不更新）
        if self._worker and isinstance(self._worker, DetectionWorker):
            self._last_op_info = dict(self._worker.op_info)
            self._last_uuid_map = dict(self._worker.uuid_map)
            self._last_send_map = dict(self._worker.send_map)

        # 通知 GUI 刷新活跃号码列表
        self._emit_cache_changed()

        # 清理线程 — 移到待清理列表保留引用，quit 后延迟清理
        if self._thread:
            thread = self._thread
            worker = self._worker
            self._thread = None
            self._worker = None
            self._dead_threads.append((thread, worker))
            thread.quit()
            QTimer.singleShot(500, self._cleanup_dead_threads)
        else:
            if self._worker:
                self._worker = None

        tab = self._mw.detection_tab
        tab.set_running(False)

        # 统计扁平化表格结果
        landed = 0
        failed = 0
        for row in range(tab.result_table.rowCount()):
            item = tab.result_table.item(row, tab.COL_LANDED)
            if not item:
                continue
            text = item.text()
            if "已落地" in text:
                landed += 1
            elif "未落地" in text or "失败" in text:
                failed += 1

        tab._success_count = landed
        tab._fail_count = failed
        tab.refresh_display()
        tab.progress_label.setText("检测完成")
        self._mw.status_bar.showMessage(
            f"检测完成 — 落地: {landed}, 失败: {failed}"
        )

    def _cleanup_dead_threads(self):
        """清理已完成的线程，只移除确认已停止的。"""
        still_alive = []
        for thread, worker in self._dead_threads:
            if thread.isRunning():
                still_alive.append((thread, worker))
            # 已停止的：不 deleteLater，让 Python GC 自然回收
        self._dead_threads = still_alive

    def shutdown(self):
        """程序关闭时安全停止所有线程。"""
        if self._worker:
            self._worker.stop()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
        for thread, worker in self._dead_threads:
            if hasattr(worker, 'stop'):
                worker.stop()
            if thread.isRunning():
                thread.quit()
                thread.wait(3000)
        self._dead_threads.clear()

    # ---------- 号码缓存管理 ----------

    def _purge_expired_cache(self):
        """移除过期的缓存号码。"""
        now = time.time()
        expired = [op for op, info in self._phone_cache.items()
                   if (now - info["time"]) >= PHONE_CACHE_TTL]
        for op in expired:
            del self._phone_cache[op]
        if expired:
            logger.debug("清理过期缓存号码: %s", expired)

    def _emit_cache_changed(self):
        """发射缓存变更信号，通知 GUI 刷新。"""
        self._purge_expired_cache()
        cache_list = []
        for op, info in self._phone_cache.items():
            cache_list.append({
                "operator": op,
                "phone": info["phone"],
                "activation_id": info["activation_id"],
                "time": info["time"],
            })
        self.phone_cache_changed.emit(cache_list)

    def get_phone_cache_list(self) -> list:
        """获取当前活跃号码缓存列表（供 GUI 初始化时调用）。"""
        self._purge_expired_cache()
        return [
            {
                "operator": op,
                "phone": info["phone"],
                "activation_id": info["activation_id"],
                "time": info["time"],
            }
            for op, info in self._phone_cache.items()
        ]

    def clear_phone_cache(self):
        """手动清空号码缓存。"""
        self._phone_cache.clear()
        self._emit_cache_changed()

    def start_retest(self):
        """复用上一轮号码，只重新测试未落地的服务器。"""
        if self._thread and self._thread.isRunning():
            self._on_status("检测正在进行中，请等待完成")
            return
        if not self._last_send_map or not self._last_eims_clients:
            self._on_status("没有上一轮检测数据，请先执行一次检测")
            return

        tab = self._mw.detection_tab

        # 找出未落地的 (srv_idx, op_idx) — 扁平化表格
        failed_pairs = []
        num_ops = len(tab._current_operators) if tab._current_operators else 1
        for row in range(tab.result_table.rowCount()):
            item = tab.result_table.item(row, tab.COL_LANDED)
            if item and ("未落地" in item.text() or "失败" in item.text()):
                srv_idx = row // num_ops
                op_idx = row % num_ops
                failed_pairs.append((srv_idx, op_idx))

        if not failed_pairs:
            self._on_status("没有未落地的项目需要重新测试")
            tab.set_running(False)
            return

        tab.set_running(True)

        self._thread = QThread()
        self._worker = RetestWorker(
            self._last_eims_clients, self._last_herosms,
            self._last_params, self._last_op_info, failed_pairs,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.cell_update.connect(self._on_cell_update, Qt.ConnectionType.QueuedConnection)
        self._worker.status_update.connect(self._on_status, Qt.ConnectionType.QueuedConnection)
        self._worker.error_occurred.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
        self._worker.detection_finished.connect(self._on_retest_finished, Qt.ConnectionType.QueuedConnection)

        self._thread.start()

    @Slot()
    def _on_retest_finished(self):
        """重测完成后更新上一轮数据。"""
        if self._worker and isinstance(self._worker, RetestWorker):
            # 合并新的 send_map 和 uuid_map
            self._last_send_map.update(self._worker.send_map)
            self._last_uuid_map.update(self._worker.uuid_map)
        self._on_finished()

    def start_recheck(self):
        """不发短信，只用上一轮 UUID 和 activation_id 重新轮询 HeroSMS。"""
        if self._thread and self._thread.isRunning():
            self._on_status("检测正在进行中，请等待完成")
            return
        if not self._last_send_map or not self._last_uuid_map:
            self._on_status("没有上一轮检测数据，请先执行一次检测")
            return

        tab = self._mw.detection_tab
        tab.set_running(True)

        eims_names = [name for name, _ in self._last_eims_clients]

        self._thread = QThread()
        self._worker = RecheckWorker(
            self._last_herosms, self._last_params,
            self._last_op_info, self._last_uuid_map,
            self._last_send_map, eims_names,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.cell_update.connect(self._on_cell_update, Qt.ConnectionType.QueuedConnection)
        self._worker.status_update.connect(self._on_status, Qt.ConnectionType.QueuedConnection)
        self._worker.error_occurred.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
        self._worker.detection_finished.connect(self._on_finished, Qt.ConnectionType.QueuedConnection)

        self._thread.start()