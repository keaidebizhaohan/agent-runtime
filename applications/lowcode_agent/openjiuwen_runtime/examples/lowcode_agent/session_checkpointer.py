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


def _redis_checkpointer_config(url: str, ttl_minutes: float | None):
    from openjiuwen.core.session.checkpointer.checkpointer import CheckpointerConfig

    conf: dict = {"connection": {"url": url}}
    if ttl_minutes is not None:
        conf["ttl"] = {
            "default_ttl": ttl_minutes,
            "refresh_on_read": _bool_env(
                "CHECKPOINTER_REFRESH_TTL_ON_READ",
                default=True,
            ),
        }
    return CheckpointerConfig(type="redis", conf=conf)


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
    # 使用 Runner 的正式配置入口。Runner.start() 会据此创建并注册 Redis
    # Checkpointer；不要在 Runner.start() 之外维护另一套隐式全局状态。
    from openjiuwen.core.runner import Runner

    runner_config = Runner.get_config().model_copy(deep=True)
    runner_config.checkpointer_config = _redis_checkpointer_config(
        url,
        ttl_minutes,
    )
    Runner.set_config(runner_config)
    _initialized = True
    logger.info(
        "Shared Redis session checkpointer configured: destination=%s, ttl_minutes=%s",
        _safe_redis_destination(url),
        ttl_minutes,
    )
    return True


def verify_session_checkpointer() -> None:
    """配置 Redis 时禁止静默回退到进程内存。"""
    url = (os.getenv("CHECKPOINTER_REDIS_URL") or "").strip()
    if not url:
        return

    from openjiuwen.core.session.checkpointer.checkpointer import CheckpointerFactory
    from openjiuwen.extensions.checkpointer.redis.checkpointer import RedisCheckpointer

    checkpointer = CheckpointerFactory.get_checkpointer()
    if not isinstance(checkpointer, RedisCheckpointer):
        raise RuntimeError(
            "CHECKPOINTER_REDIS_URL is configured, but Runner did not start "
            f"with RedisCheckpointer (actual={type(checkpointer).__name__})"
        )
    logger.info(
        "Shared Redis session checkpointer is active: destination=%s",
        _safe_redis_destination(url),
    )
