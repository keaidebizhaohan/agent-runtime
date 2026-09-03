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
    checkpointer = object()
    create = AsyncMock(return_value=checkpointer)
    set_default = Mock()
    monkeypatch.setattr(session_checkpointer, "_ping_redis", ping)
    monkeypatch.setattr(session_checkpointer, "_create_redis_checkpointer", create)

    import openjiuwen.core.session.checkpointer.checkpointer as checkpointer_module

    monkeypatch.setattr(
        checkpointer_module.CheckpointerFactory,
        "set_default_checkpointer",
        set_default,
    )

    assert await session_checkpointer.init_session_checkpointer() is True
    ping.assert_awaited_once_with("redis://redis:6379/0")
    create.assert_awaited_once_with("redis://redis:6379/0", 60.0)
    set_default.assert_called_once_with(checkpointer)


def test_invalid_ttl_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("CHECKPOINTER_DEFAULT_TTL_MINUTES", "0")

    with pytest.raises(ValueError, match="must be greater than 0"):
        session_checkpointer._positive_float_env(
            "CHECKPOINTER_DEFAULT_TTL_MINUTES"
        )
