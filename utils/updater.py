"""GitHub 自动更新模块。

通过对比本地 git commit 与 GitHub 远程最新 commit 判断是否有更新，
有更新时通过 git pull 拉取最新代码。
"""

import subprocess
import urllib.request
import json

GITHUB_REPO = "over958999-byte/King99"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/commits/main"


def get_local_commit() -> str | None:
    """获取本地 HEAD commit hash，失败返回 None。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_remote_commit() -> str | None:
    """通过 GitHub API 获取远程 main 分支最新 commit hash。"""
    req = urllib.request.Request(
        GITHUB_API_URL,
        headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "King99-Updater"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("sha")
    except Exception:
        pass
    return None


def check_for_update() -> dict:
    """检查是否有更新。

    返回:
        {"has_update": bool, "local": str|None, "remote": str|None}
    """
    local = get_local_commit()
    remote = get_remote_commit()
    has_update = (
        local is not None
        and remote is not None
        and local != remote
    )
    return {"has_update": has_update, "local": local, "remote": remote}


def pull_update() -> dict:
    """执行 git pull 拉取最新代码。

    返回:
        {"success": bool, "message": str}
    """
    try:
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            return {"success": True, "message": result.stdout.strip()}
        else:
            return {"success": False, "message": result.stderr.strip() or result.stdout.strip()}
    except Exception as e:
        return {"success": False, "message": str(e)}
