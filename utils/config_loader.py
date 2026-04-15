import copy
import json
import os


CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")

DEFAULT_CONFIG = {
    "herosms": {
        "api_key": "",
        "base_url": "https://hero-sms.com/stubs/handler_api.php",
    },
    "eims_servers": [],
    "settings": {
        "check_interval": 5,
        "timeout": 120,
        "max_retries": 3,
    },
}


def load_config(path: str = None) -> dict:
    """加载 JSON 配置文件，文件不存在或损坏时返回默认配置并自动创建。"""
    path = path or CONFIG_PATH
    if not os.path.exists(path):
        save_config(DEFAULT_CONFIG, path)
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(config: dict, path: str = None) -> None:
    """将配置字典保存到 JSON 文件。"""
    path = path or CONFIG_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
