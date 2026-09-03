# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

"""Low-code Agent 会话 Checkpointer 初始化。"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger("lowcode_agent")

_initialized = False


def _positive_float_env(name: str) -> float | None:
    raw_value = (os.getenv(name) or "").strip()
    if not raw_value:
        return None
    value = float(raw_value)
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return value


def _bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_redis_destination(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "unknown"
    port = parsed.port or 6379
    database = parsed.path.lstrip("/") or "0"
    return f"{host}:{port}/{database}"


async def _ping_redis(url: str) -> None:
    """在 Pod 就绪前确认 Redis 可用，避免运行到首次对话才报错。"""
    from redis.asyncio import Redis

    client = Redis.from_url(url)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _create_redis_checkpointer(url: str, ttl_minutes: float | None):
    # 导入模块会执行 RedisCheckpointerFactory.register("redis")。
    import openjiuwen.extensions.checkpointer.redis.checkpointer  # noqa: F401
    from openjiuwen.core.session.checkpointer.checkpointer import (
        CheckpointerConfig,
        CheckpointerFactory,
    )

    conf: dict = {"connection": {"url": url}}
    if ttl_minutes is not None:
        conf["ttl"] = {
            "default_ttl": ttl_minutes,
            "refresh_on_read": _bool_env(
                "CHECKPOINTER_REFRESH_TTL_ON_READ",
                default=True,
            ),
        }
    return await CheckpointerFactory.create(
        CheckpointerConfig(type="redis", conf=conf)
    )


async def init_session_checkpointer() -> bool:
    """
    配置共享 Redis Checkpointer。

    Returns:
        True 表示使用 Redis；False 表示未配置 URL，保持 SDK 内存模式。
    """
    global _initialized
    if _initialized:
        return bool((os.getenv("CHECKPOINTER_REDIS_URL") or "").strip())

    url = (os.getenv("CHECKPOINTER_REDIS_URL") or "").strip()
    if not url:
        logger.info(
            "CHECKPOINTER_REDIS_URL is not configured; session storage uses process memory"
        )
        _initialized = True
        return False

    ttl_minutes = _positive_float_env("CHECKPOINTER_DEFAULT_TTL_MINUTES")
    await _ping_redis(url)
    checkpointer = await _create_redis_checkpointer(url, ttl_minutes)

    from openjiuwen.core.session.checkpointer.checkpointer import CheckpointerFactory

    CheckpointerFactory.set_default_checkpointer(checkpointer)
    _initialized = True
    logger.info(
        "Shared Redis session checkpointer initialized: destination=%s, ttl_minutes=%s",
        _safe_redis_destination(url),
        ttl_minutes,
    )
    return True
