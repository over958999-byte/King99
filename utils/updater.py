"""GitHub 自动更新模块。

直接 git pull 拉取最新代码，根据输出判断是否有变化。
启动前验证 GitHub 仓库是否可访问。
"""

import subprocess
import urllib.request

GITHUB_REPO = "over958999-byte/King99"
GITHUB_REPO_API = f"https://api.github.com/repos/{GITHUB_REPO}"


def verify_repo() -> dict:
    """验证 GitHub 仓库是否存在且可访问。

    返回:
        {"ok": bool, "reason": str}
        - ok=True: 仓库可访问
        - ok=False, reason="not_found": 仓库不存在或已删除
        - ok=False, reason="network": 网络异常
    """
    req = urllib.request.Request(
        GITHUB_REPO_API,
        headers={"User-Agent": "King99-Updater"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return {"ok": True, "reason": ""}
            return {"ok": False, "reason": "not_found"}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ok": False, "reason": "not_found"}
        return {"ok": False, "reason": "network"}
    except Exception:
        return {"ok": False, "reason": "network"}


def pull_update() -> dict:
    """执行 git pull 拉取最新代码。

    返回:
        {"has_update": bool, "success": bool, "message": str}
        - has_update: 是否有新代码被拉取
        - success: 命令是否执行成功
        - message: git 输出信息
    """
    try:
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            capture_output=True, text=True, timeout=60,
        )
        output = result.stdout.strip()
        if result.returncode == 0:
            has_update = "Already up to date" not in output
            return {"has_update": has_update, "success": True, "message": output}
        else:
            return {"has_update": False, "success": False, "message": result.stderr.strip() or output}
    except Exception as e:
        return {"has_update": False, "success": False, "message": str(e)}
