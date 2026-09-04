# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

from unittest.mock import AsyncMock, Mock

import pytest

from openjiuwen_runtime.examples.lowcode_agent import session_checkpointer


@pytest.fixture(autouse=True)
def reset_initialization(monkeypatch):
    monkeypatch.setattr(session_checkpointer, "_initialized", False)
    monkeypatch.delenv("CHECKPOINTER_REDIS_URL", raising=False)
    monkeypatch.delenv("CHECKPOINTER_DEFAULT_TTL_MINUTES", raising=False)
    monkeypatch.delenv("CHECKPOINTER_REFRESH_TTL_ON_READ", raising=False)


@pytest.mark.asyncio
async def test_missing_redis_url_keeps_in_memory_mode(monkeypatch) -> None:
    ping = AsyncMock()
    monkeypatch.setattr(session_checkpointer, "_ping_redis", ping)

    assert await session_checkpointer.init_session_checkpointer() is False
    ping.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_url_initializes_shared_checkpointer(monkeypatch) -> None:
    monkeypatch.setenv("CHECKPOINTER_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("CHECKPOINTER_DEFAULT_TTL_MINUTES", "60")
    ping = AsyncMock()
    monkeypatch.setattr(session_checkpointer, "_ping_redis", ping)

    from openjiuwen.core.runner import Runner
    from openjiuwen.core.runner.runner_config import RunnerConfig

    runner_config = RunnerConfig(distributed_mode=False)
    get_config = Mock(return_value=runner_config)
    set_config = Mock()
    monkeypatch.setattr(Runner, "get_config", get_config)
    monkeypatch.setattr(Runner, "set_config", set_config)

    assert await session_checkpointer.init_session_checkpointer() is True
    ping.assert_awaited_once_with("redis://redis:6379/0")
    get_config.assert_called_once_with()
    configured_runner = set_config.call_args.args[0]
    assert configured_runner.checkpointer_config.type == "redis"
    assert configured_runner.checkpointer_config.conf == {
        "connection": {"url": "redis://redis:6379/0"},
        "ttl": {"default_ttl": 60.0, "refresh_on_read": True},
    }


def test_verify_rejects_silent_in_memory_fallback(monkeypatch) -> None:
    monkeypatch.setenv("CHECKPOINTER_REDIS_URL", "redis://redis:6379/0")

    from openjiuwen.core.session.checkpointer.checkpointer import CheckpointerFactory
    from openjiuwen.core.session.checkpointer.inmemory import InMemoryCheckpointer

    monkeypatch.setattr(
        CheckpointerFactory,
        "get_checkpointer",
        Mock(return_value=InMemoryCheckpointer()),
    )

    with pytest.raises(RuntimeError, match="did not start with RedisCheckpointer"):
        session_checkpointer.verify_session_checkpointer()


def test_invalid_ttl_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("CHECKPOINTER_DEFAULT_TTL_MINUTES", "0")

    with pytest.raises(ValueError, match="must be greater than 0"):
        session_checkpointer._positive_float_env(
            "CHECKPOINTER_DEFAULT_TTL_MINUTES"
        )
