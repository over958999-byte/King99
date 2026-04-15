"""HeroSMS 虚拟号码 API 客户端模块。

兼容 sms-activate 协议，提供获取号码、查询状态、取消/完成激活、
查询国家/服务/价格等功能。支持多账号及自定义服务地址。
"""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


# ---------- 自定义异常 ----------

class HeroSMSError(Exception):
    """HeroSMS API 错误基类。"""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message or ERROR_MESSAGES.get(code, code)
        super().__init__(self.message)


class HeroSMSAuthError(HeroSMSError):
    """认证错误（BAD_KEY）。"""


class HeroSMSBalanceError(HeroSMSError):
    """余额不足（NO_BALANCE）。"""


class HeroSMSNoNumberError(HeroSMSError):
    """暂无可用号码（NO_NUMBERS）。"""


class HeroSMSActivationError(HeroSMSError):
    """激活操作错误（NO_ACTIVATION / WRONG_ACTIVATION_ID 等）。"""


# ---------- 错误码映射 ----------

ERROR_MESSAGES = {
    "BAD_KEY": "API Key 无效",
    "BAD_ACTION": "请求格式错误",
    "BAD_LANG": "语言参数无效",
    "NO_ACTIVATION": "激活 ID 无效或已过期",
    "NO_BALANCE": "余额不足",
    "NO_NUMBERS": "暂无可用号码",
    "ERROR_SQL": "服务端数据库错误",
    "REQUEST_LIMIT": "请求频率超限",
    "WRONG_ACTIVATION_ID": "激活 ID 无效",
    "CANNOT_BEFORE_2_MIN": "激活后 2 分钟内不可取消",
    "WRONG_MAX_PRICE": "价格超出限制",
    "WRONG_SERVICE": "服务代码无效",
    "WRONG_COUNTRY": "国家 ID 无效",
}

# 错误码到异常类的映射
_ERROR_CLASS_MAP = {
    "BAD_KEY": HeroSMSAuthError,
    "NO_BALANCE": HeroSMSBalanceError,
    "NO_NUMBERS": HeroSMSNoNumberError,
    "NO_ACTIVATION": HeroSMSActivationError,
    "WRONG_ACTIVATION_ID": HeroSMSActivationError,
    "CANNOT_BEFORE_2_MIN": HeroSMSActivationError,
}


# ---------- 客户端类 ----------

class HeroSMSClient:
    """HeroSMS 虚拟号码 API 客户端。

    每个实例对应一个 HeroSMS 账号（API Key）。
    兼容 sms-activate 协议。

    所有业务方法在 API 返回错误时抛出 HeroSMSError 或其子类。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://hero-sms.com/stubs/handler_api.php",
        name: str = "",
        timeout: int = 30,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.name = name or f"HeroSMS-{api_key[:8]}..."
        self.timeout = timeout

    # ---------- 内部方法 ----------

    def _request(self, action: str, extra_params: dict = None) -> requests.Response:
        """发送 GET 请求到 API。"""
        params = {
            "api_key": self.api_key,
            "action": action,
        }
        if extra_params:
            params.update(extra_params)
        try:
            resp = requests.get(
                self.base_url, params=params, timeout=self.timeout
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            logger.error(
                "HeroSMS 请求失败 [%s] action=%s: %s", self.name, action, e
            )
            raise

    def _check_text_error(self, text: str) -> None:
        """检查纯文本响应是否为错误码，是则抛出对应异常。"""
        text = text.strip()
        # 处理带冒号的错误如 WRONG_MAX_PRICE:0.5
        code = text.split(":")[0]
        if code in ERROR_MESSAGES:
            exc_cls = _ERROR_CLASS_MAP.get(code, HeroSMSError)
            raise exc_cls(code)

    def _check_json_error(self, data: dict) -> None:
        """检查 JSON 响应是否包含错误，是则抛出对应异常。"""
        if isinstance(data, dict) and "error" in data:
            code = data["error"]
            exc_cls = _ERROR_CLASS_MAP.get(code, HeroSMSError)
            raise exc_cls(code)

    def _request_text(self, action: str, extra_params: dict = None) -> str:
        """发送请求并返回纯文本响应（已做错误检查）。"""
        resp = self._request(action, extra_params)
        text = resp.text.strip()
        self._check_text_error(text)
        return text

    def _request_json(self, action: str, extra_params: dict = None) -> dict | list:
        """发送请求并返回 JSON 响应（已做错误检查）。

        如果响应不是合法 JSON，按纯文本错误处理。
        """
        resp = self._request(action, extra_params)
        try:
            data = resp.json()
        except ValueError:
            text = resp.text.strip()
            self._check_text_error(text)
            raise HeroSMSError("PARSE_ERROR", f"响应格式异常: {text}")
        if isinstance(data, dict):
            self._check_json_error(data)
        return data

    # ---------- 业务接口 ----------

    def get_balance(self) -> float:
        """查询账户余额。

        Returns:
            余额金额（浮点数）。

        Raises:
            HeroSMSError: API 返回错误。
        """
        text = self._request_text("getBalance")
        # 响应格式: ACCESS_BALANCE:123.45
        if text.startswith("ACCESS_BALANCE:"):
            try:
                return float(text.split(":", 1)[1])
            except ValueError:
                pass
        raise HeroSMSError("PARSE_ERROR", f"余额响应格式异常: {text}")

    def get_number(
        self,
        service: str,
        country: int,
        *,
        operator: str = "",
        max_price: float = 0,
        phone_exception: str = "",
    ) -> dict:
        """获取虚拟号码（getNumberV2，返回 JSON）。

        Args:
            service: 服务代码（如 "tg" 表示 Telegram）。
            country: 国家 ID。
            operator: 运营商代码，可选。
            max_price: 最大可接受价格，0 表示不限。
            phone_exception: 排除的号码前缀，可选。

        Returns:
            dict，包含:
                activationId (int), phoneNumber (str), activationCost (float),
                currency (int), countryCode (str), canGetAnotherSms (int),
                activationTime (str), activationOperator (str)

        Raises:
            HeroSMSNoNumberError: 暂无可用号码。
            HeroSMSBalanceError: 余额不足。
            HeroSMSError: 其他 API 错误。
        """
        params = {
            "service": service,
            "country": str(country),
        }
        if operator:
            params["operator"] = operator
        if max_price > 0:
            params["maxPrice"] = str(max_price)
        if phone_exception:
            params["phoneException"] = phone_exception

        return self._request_json("getNumberV2", params)

    def get_status(self, activation_id: int) -> str:
        """查询激活状态（简单文本版）。

        Args:
            activation_id: 激活 ID。

        Returns:
            状态文本，如:
                "STATUS_WAIT_CODE" — 等待验证码
                "STATUS_CANCEL" — 已取消
                "STATUS_OK:<code>" — 已收到验证码，<code> 为验证码内容

        Raises:
            HeroSMSActivationError: 激活 ID 无效。
            HeroSMSError: 其他 API 错误。
        """
        return self._request_text("getStatus", {"id": str(activation_id)})

    def get_status_v2(self, activation_id: int) -> dict:
        """查询激活状态（V2 版，返回 JSON，含短信/语音详情）。

        Args:
            activation_id: 激活 ID。

        Returns:
            dict，包含:
                status (str), sms (dict/list), call (dict),
                verificationType (int: 0=短信, 1=来电号码, 2=语音)
            其中 sms 可能包含: code, text, dateTime

        Raises:
            HeroSMSActivationError: 激活 ID 无效。
            HeroSMSError: 其他 API 错误。
        """
        resp = self._request("getStatusV2", {"id": str(activation_id)})
        # 先尝试 JSON 解析
        try:
            data = resp.json()
        except ValueError:
            # 某些 sms-activate 兼容实现可能返回纯文本（如 STATUS_WAIT_CODE）
            text = resp.text.strip()
            self._check_text_error(text)
            # 将文本状态转为 dict 格式，保持与 JSON 响应一致
            if text.startswith("STATUS_OK:"):
                code = text.split(":", 1)[1]
                return {"status": "STATUS_OK", "sms": {"code": code, "text": code}}
            return {"status": text, "sms": {}}
        if isinstance(data, dict):
            self._check_json_error(data)
        return data

    def get_all_sms(self, activation_id: int) -> list:
        """获取激活收到的所有短信（getAllSms）。

        Args:
            activation_id: 激活 ID。

        Returns:
            短信列表，每项为 dict，包含短信详情。

        Raises:
            HeroSMSActivationError: 激活 ID 无效。
            HeroSMSError: 其他 API 错误。
        """
        data = self._request_json("getAllSms", {"id": str(activation_id)})
        if isinstance(data, dict):
            return data.get("data", [])
        if isinstance(data, list):
            return data
        return []

    def set_status(self, activation_id: int, status: int) -> str:
        """设置激活状态。

        Args:
            activation_id: 激活 ID。
            status: 状态码:
                1 = 通知已准备好（已发送验证码请求）
                3 = 请求再次发送短信
                6 = 完成激活
                8 = 取消激活

        Returns:
            操作结果文本，如:
                "ACCESS_READY" — 号码准备就绪
                "ACCESS_RETRY_GET" — 已请求重发
                "ACCESS_ACTIVATION" — 激活已完成
                "ACCESS_CANCEL" — 激活已取消

        Raises:
            HeroSMSActivationError: 激活 ID 无效或不可取消。
            HeroSMSError: 其他 API 错误。
        """
        return self._request_text(
            "setStatus", {"id": str(activation_id), "status": str(status)}
        )

    def get_active_activations(self, start: int = 0, limit: int = 100) -> list:
        """获取当前活跃的激活列表。

        Args:
            start: 偏移量，默认 0。
            limit: 最大返回数量，最大 100。

        Returns:
            激活信息列表，每项为 dict，包含:
                activationId, serviceCode, phoneNumber, activationStatus,
                activationTime, countryCode, countryName 等。

        Raises:
            HeroSMSError: API 返回错误。
        """
        params = {"start": str(start), "limit": str(min(limit, 100))}
        data = self._request_json("getActiveActivations", params)
        if isinstance(data, dict):
            return data.get("data", [])
        return data

    def cancel_activation(self, activation_id: int) -> str:
        """取消激活（释放号码）。

        注意：激活后 2 分钟内不可取消。

        Args:
            activation_id: 激活 ID。

        Returns:
            "ACCESS_CANCEL" 表示成功。

        Raises:
            HeroSMSActivationError: 不可取消（如未满 2 分钟）。
        """
        return self.set_status(activation_id, 8)

    def finish_activation(self, activation_id: int) -> str:
        """完成激活（确认已收到验证码）。

        Args:
            activation_id: 激活 ID。

        Returns:
            "ACCESS_ACTIVATION" 表示成功。
        """
        return self.set_status(activation_id, 6)

    def get_countries(self, lang: str = "cn") -> list:
        """获取可用国家列表。

        Args:
            lang: 语言代码，默认 "cn"（中文）。

        Returns:
            国家信息列表，每项为 dict，通常包含:
                id (int), name (str), code (str) 等。

        Raises:
            HeroSMSError: API 返回错误。
        """
        data = self._request_json("getCountries", {"lang": lang})
        # API 可能返回 dict（以 ID 为 key）或 list
        if isinstance(data, dict):
            result = []
            for country_id, info in data.items():
                if isinstance(info, dict):
                    info["id"] = int(country_id)
                    result.append(info)
                else:
                    result.append({"id": int(country_id), "info": info})
            return result
        return data

    def get_operators(self, country: int = None) -> dict:
        """获取运营商列表。

        Args:
            country: 国家 ID，可选。不传则返回所有国家的运营商。

        Returns:
            运营商信息字典，通常以国家 ID 为 key。

        Raises:
            HeroSMSError: API 返回错误。
        """
        params = {}
        if country is not None:
            params["country"] = str(country)
        return self._request_json("getOperators", params)

    def get_services(self, country: int = None, lang: str = "cn") -> list:
        """获取可用服务列表。

        Args:
            country: 国家 ID，可选。不传则返回所有服务。
            lang: 语言代码，默认 "cn"（中文）。

        Returns:
            服务信息列表，每项为 dict，通常包含:
                code (str), name (str) 等。

        Raises:
            HeroSMSError: API 返回错误。
        """
        params = {"lang": lang}
        if country is not None:
            params["country"] = str(country)
        data = self._request_json("getServicesList", params)
        # API 可能返回 dict（以服务代码为 key）或 list
        if isinstance(data, dict):
            result = []
            for svc_code, info in data.items():
                if isinstance(info, dict):
                    info["code"] = svc_code
                    result.append(info)
                else:
                    result.append({"code": svc_code, "info": info})
            return result
        return data

    def get_prices(self, service: str = None, country: int = None) -> list:
        """获取价格信息。

        Args:
            service: 服务代码，可选。
            country: 国家 ID，可选。

        Returns:
            价格信息列表，每项为 dict。

        Raises:
            HeroSMSError: API 返回错误。
        """
        params = {}
        if service is not None:
            params["service"] = service
        if country is not None:
            params["country"] = str(country)
        data = self._request_json("getPrices", params)
        # API 返回嵌套 dict: {country_id: {service_code: {cost, count, ...}}}
        if isinstance(data, dict):
            result = []
            for country_id, services in data.items():
                if not isinstance(services, dict):
                    continue
                for svc_code, price_info in services.items():
                    entry = {"country": country_id, "service": svc_code}
                    if isinstance(price_info, dict):
                        entry.update(price_info)
                    else:
                        entry["price"] = price_info
                    result.append(entry)
            return result
        return data

    def __repr__(self) -> str:
        return f"HeroSMSClient(name={self.name!r}, url={self.base_url!r})"


# ---------- 工厂函数 ----------

def create_client_from_config(config: dict) -> HeroSMSClient | None:
    """从配置创建单个 HeroSMS 客户端。

    Args:
        config: 完整的配置字典（含 herosms 段）。

    Returns:
        HeroSMSClient 实例，若 api_key 为空则返回 None。
    """
    herosms = config.get("herosms", {})
    api_key = herosms.get("api_key", "")
    base_url = herosms.get("base_url", "https://hero-sms.com/stubs/handler_api.php")
    if not api_key:
        return None
    return HeroSMSClient(api_key=api_key, base_url=base_url)
