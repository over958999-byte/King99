"""EJOIN EIMS HTTP API v3.5 客户端模块。

支持多服务器多账号，提供发送短信、查询余额、查询发送报告、接收短信等功能。
基地址: http://{IP}:20003/  编码: UTF-8
"""

import base64
import hashlib
import logging
import time

import requests

logger = logging.getLogger(__name__)

# EIMS API 状态码映射
STATUS_MESSAGES = {
    0: "成功",
    -1: "认证错误",
    -2: "IP 访问受限",
    -3: "短信内容含有敏感字符",
    -4: "短信内容为空",
    -5: "短信内容过长",
    -6: "不是模板的短信",
    -7: "号码个数过多",
    -8: "号码为空",
    -9: "号码异常",
    -10: "该通道余额不足",
    -11: "定时时间格式不对",
    -12: "平台错误，请与管理员联系",
    -13: "用户被锁定",
}

# 发送状态码映射（getreport 中 array 的发送状态字段）
SEND_STATUS_MESSAGES = {
    0: "发送成功",
    1: "未发送",
    2: "正在发送",
    1001: "没有路由",
    1002: "没有通道",
    1003: "余额不足",
    1004: "未知",
    1005: "对端拒绝发送",
    1006: "对端发送超时",
    1007: "服务端发送超时",
    1008: "供应商没有费率",
    1009: "消费用户没有费率",
    1010: "没有供应商",
    1011: "黑号码限制",
    1012: "敏感词限制",
    1013: "每天发送数限制",
    1014: "号码 MccMnc 找不到",
    1016: "短信模板限制",
    1017: "供应商余额不足",
    1018: "用户利润不足",
    1019: "通道利润不足",
    1020: "MccMnc 号码长度限制",
    1021: "没找到任务",
    1022: "中国短信受限",
    1023: "路由 MccMnc 限制",
}

# 送达状态码映射（getreport 中 array 的送达状态字段）
DELIVER_STATUS_MESSAGES = {
    0: "不需要报告",
    1: "已发送但未送达",
    2: "送达失败",
    3: "送达成功",
    4: "送达超时",
    5: "其他未知状态",
}


class EIMSClient:
    """EJOIN EIMS HTTP API v3.5 客户端。

    每个实例对应一个 EIMS 服务器账号连接。
    支持明文密码和 MD5 加密两种认证方式。
    """

    def __init__(
        self,
        host: str,
        port: int = 20003,
        account: str = "",
        password: str = "",
        use_md5: bool = False,
        protocol_key: str = "",
        timeout: int = 30,
    ):
        self.host = host
        self.port = port
        self.account = account
        self.password = password
        self.use_md5 = use_md5
        self.protocol_key = protocol_key
        self.timeout = timeout
        self._seq = 1
        self._base_url = f"http://{host}:{port}"

    def _get_auth_params(self) -> dict:
        """根据配置返回认证参数（明文或 MD5）。"""
        params = {"account": self.account}
        if self.use_md5 and self.protocol_key:
            ts = int(time.time())
            raw = f"{self.account}{self.password}{self._seq}{ts}{self.protocol_key}"
            md5_pwd = hashlib.md5(raw.encode("utf-8")).hexdigest()
            params["password"] = md5_pwd
            params["seq"] = self._seq
            params["time"] = ts
            self._seq += 1
        else:
            params["password"] = self.password
        return params

    def _request_get(self, endpoint: str, extra_params: dict = None) -> dict:
        """发送 GET 请求并返回 JSON 响应。"""
        url = f"{self._base_url}/{endpoint}"
        params = self._get_auth_params()
        if extra_params:
            params.update(extra_params)
        try:
            resp = requests.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(
                "EIMS GET 请求失败 [%s:%s] %s: %s",
                self.host, self.port, endpoint, e,
            )
            raise
        try:
            return resp.json()
        except ValueError:
            logger.error(
                "EIMS GET 响应非 JSON [%s:%s] %s: %s",
                self.host, self.port, endpoint, resp.text[:200],
            )
            return {"status": -99, "error": "响应格式异常"}

    def _request_post(self, endpoint: str, body: dict) -> dict:
        """发送 POST 请求并返回 JSON 响应。"""
        url = f"{self._base_url}/{endpoint}"
        auth = self._get_auth_params()
        merged = {**body, **auth}
        headers = {"Content-Type": "application/json;charset=utf-8"}
        try:
            resp = requests.post(
                url, json=merged, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(
                "EIMS POST 请求失败 [%s:%s] %s: %s",
                self.host, self.port, endpoint, e,
            )
            raise
        try:
            return resp.json()
        except ValueError:
            logger.error(
                "EIMS POST 响应非 JSON [%s:%s] %s: %s",
                self.host, self.port, endpoint, resp.text[:200],
            )
            return {"status": -99, "error": "响应格式异常"}

    def get_balance(self) -> dict:
        """查询账户余额。

        返回示例: {"status": 0, "balance": "99.990000", "gift": "50.00000"}
        status: 0=成功, -1=认证错误, -2=IP访问受限
        """
        return self._request_get("getbalance")

    def send_sms(
        self,
        numbers: str,
        content: str,
        smstype: int = 0,
        sender: str = "",
    ) -> dict:
        """发送短信（POST 方式，支持多号码单内容）。

        Args:
            numbers: 接收号码，多个号码用英文逗号分隔（POST 最多 10000 个）。
            content: 短信内容，长度不超过 1024。
            smstype: 短信类型，0=普通短信，1=彩信。
            sender: 发件人，可选。

        返回示例: {"status": 0, "success": 2, "fail": 0, "array": [[10010,1], [1008611,2]]}
        array 中每项为 [号码, 发送ID]，发送ID后续用于 get_report 查询。
        """
        body = {
            "content": content,
            "smstype": smstype,
            "numbers": numbers,
        }
        if sender:
            body["sender"] = sender

        return self._request_post("sendsms", body)

    def get_report(self, ids: list) -> dict:
        """查询短信发送结果。

        Args:
            ids: 发送 ID 列表（由 send_sms 返回），最多 200 个。

        返回示例:
        {
            "status": 0, "success": 1, "fail": 1, "unsent": 0, "sending": 0,
            "deliverSuc": 0, "deliverFail": 0, "deliverTimeout": 0, "nofound": 0,
            "array": [[1,"10010",20171001123015,0,0,0], [2,"1008611",20171001123015,0,20171001123025,3]]
        }
        array 格式: [查询ID, 号码, 发送时间, 发送状态, 送达时间, 送达状态]
        发送状态: 0=成功, 1=未发送, 2=正在发送, 其他=失败
        送达状态: 0=不需要报告, 1=已发送未送达, 2=送达失败, 3=送达成功, 4=送达超时
        """
        if not ids:
            return {"status": 0, "success": 0, "fail": 0, "array": []}
        ids_str = ",".join(str(i) for i in ids)
        return self._request_get("getreport", {"ids": ids_str})

    def get_sms(self, start_time: int = 0) -> dict:
        """查询接收到的短信。

        Args:
            start_time: 开始查询的时间戳。0 表示不限制。

        返回示例:
        {"status": 0, "cnt": 2, "array": [[1,"10010","123456",20171001123015,"base64内容"]]}
        注意: array 中短信内容字段为 base64 编码，需用 decode_sms_content() 解码。
        """
        extra = {}
        if start_time:
            extra["start_time"] = start_time
        return self._request_get("getsms", extra)

    def __repr__(self) -> str:
        return (
            f"EIMSClient(host={self.host!r}, port={self.port}, "
            f"account={self.account!r})"
        )


def decode_sms_content(b64_content: str) -> str:
    """将 getsms 返回的 base64 编码短信内容解码为 UTF-8 文本。"""
    try:
        return base64.b64decode(b64_content).decode("utf-8")
    except Exception:
        return b64_content


def get_status_message(status: int) -> str:
    """根据 API 状态码获取中文描述。"""
    return STATUS_MESSAGES.get(status, f"未知状态({status})")


def get_send_status_message(status: int) -> str:
    """根据发送状态码获取中文描述。"""
    return SEND_STATUS_MESSAGES.get(status, f"发送失败({status})")


def get_deliver_status_message(status: int) -> str:
    """根据送达状态码获取中文描述。"""
    return DELIVER_STATUS_MESSAGES.get(status, f"未知送达状态({status})")


def create_clients_from_config(config: dict) -> list[EIMSClient]:
    """从配置字典创建所有 EIMS 客户端实例。

    Args:
        config: 完整的配置字典（含 eims_servers 段）。

    Returns:
        EIMSClient 列表（跳过 host 为空的条目）。
    """
    clients = []
    servers = config.get("eims_servers", [])
    settings = config.get("settings", {})
    default_timeout = settings.get("timeout", 30)

    for srv in servers:
        host = srv.get("host", "")
        if not host:
            continue
        client = EIMSClient(
            host=host,
            port=srv.get("port", 20003),
            account=srv.get("username", ""),
            password=srv.get("password", ""),
            use_md5=srv.get("md5_auth", False),
            protocol_key=srv.get("protocol_key", ""),
            timeout=default_timeout,
        )
        clients.append(client)
        logger.info("已创建 EIMS 客户端: %s", client)

    return clients
