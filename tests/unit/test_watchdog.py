from __future__ import annotations

import signal

import pytest

from main import _watchdog


def test_watchdog_sets_and_cancels_alarm() -> None:
    _watchdog(minutes=1)
    # 立即取消，验证已设置且清理干净（不实际等待超时）
    pending = signal.alarm(0)
    assert pending > 0  # watchdog 已注册 SIGALRM 定时器
    signal.signal(signal.SIGALRM, signal.SIG_DFL)


def test_watchdog_handler_forces_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    exits = []
    monkeypatch.setattr("os._exit", lambda code: exits.append(code))
    _watchdog(minutes=1)
    handler = signal.getsignal(signal.SIGALRM)
    signal.alarm(0)
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    handler(signal.SIGALRM, None)  # 模拟超时触发
    assert exits == [99]
