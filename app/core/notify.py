"""macOS notification for failed runs (respect IAI_NO_NOTIFY=1 in tests/CI)."""

from __future__ import annotations

import os
import subprocess


def notify(title: str, message: str) -> None:
    if os.environ.get("IAI_NO_NOTIFY") == "1":
        return
    try:
        script = 'display notification "%s" with title "%s"' % (
            message.replace('"', "'")[:180], title.replace('"', "'")
        )
        subprocess.run(["osascript", "-e", script], timeout=5, check=False)
    except Exception:
        pass  # 通知失败绝不影响主流程
