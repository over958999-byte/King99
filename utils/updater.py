"""GitHub 自动更新模块。

直接 git pull 拉取最新代码，根据输出判断是否有变化。
"""

import subprocess


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
