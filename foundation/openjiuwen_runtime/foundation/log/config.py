# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

import logging
import logging.config
import os
from pathlib import Path
from typing import Any, Optional

import yaml

_config_loaded: bool = False

# 环境变量（供 Gateway / AgentServer 等宿主进程在 import runtime SDK 前注入）
ENV_LOG_CONFIG = "OPENJIUWEN_RUNTIME_LOG_CONFIG"
ENV_LOG_FILE = "OPENJIUWEN_RUNTIME_LOG_FILE"
ENV_LOG_DIR = "OPENJIUWEN_RUNTIME_LOG_DIR"

_DEFAULT_LOG_DIR_FILENAME = "openjiuwen_runtime.log"


def get_config_path() -> Path:
    """获取日志配置文件路径。

    优先 ``OPENJIUWEN_RUNTIME_LOG_CONFIG``，否则使用 SDK 内置 ``config/logging.yaml``。
    """
    override = os.getenv(ENV_LOG_CONFIG, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    current_dir = Path(__file__).parent
    return current_dir.parent / "config" / "logging.yaml"


def _resolve_log_file(raw: str) -> str:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return str(path.resolve())
    log_dir = os.getenv(ENV_LOG_DIR, "").strip()
    if log_dir:
        return str((Path(log_dir).expanduser().resolve() / path).resolve())
    return str((Path.cwd() / path).resolve())


def _pick_log_file_override(explicit: Optional[str] = None) -> Optional[str]:
    if explicit and explicit.strip():
        return _resolve_log_file(explicit.strip())
    env_file = os.getenv(ENV_LOG_FILE, "").strip()
    if env_file:
        return _resolve_log_file(env_file)
    log_dir = os.getenv(ENV_LOG_DIR, "").strip()
    if log_dir:
        return str((Path(log_dir).expanduser().resolve() / _DEFAULT_LOG_DIR_FILENAME).resolve())
    return None


def _apply_log_file_override(config: dict[str, Any], log_file: Optional[str] = None) -> dict[str, Any]:
    """将 file handler 的输出路径替换为调用方指定位置。"""
    resolved = _pick_log_file_override(log_file)
    if not resolved:
        return config

    handlers = config.get("handlers")
    if not isinstance(handlers, dict) or "file" not in handlers:
        return config

    patched = dict(config)
    patched_handlers = dict(handlers)
    file_handler = dict(patched_handlers["file"])
    file_handler["filename"] = resolved
    patched_handlers["file"] = file_handler
    patched["handlers"] = patched_handlers
    return patched


def setup_logging(
    config_path: Optional[str] = None,
    *,
    log_file: Optional[str] = None,
) -> None:
    """初始化日志配置（进程内仅生效一次）。

    Args:
        config_path: 日志配置文件路径；默认 ``get_config_path()``。
        log_file: 覆盖 YAML 中 ``handlers.file.filename``；也可通过
            ``OPENJIUWEN_RUNTIME_LOG_FILE`` / ``OPENJIUWEN_RUNTIME_LOG_DIR`` 注入。
    """
    global _config_loaded

    if _config_loaded:
        return

    if config_path is None:
        config_path = str(get_config_path())

    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
            config = _apply_log_file_override(config, log_file=log_file)
            logging.config.dictConfig(config)
    else:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(funcName)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        resolved = _pick_log_file_override(log_file)
        if resolved:
            root = logging.getLogger()
            file_handler = logging.FileHandler(resolved, encoding="utf-8")
            file_handler.setFormatter(
                logging.Formatter(
                    fmt="%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(funcName)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
            root.addHandler(file_handler)

    _config_loaded = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    获取日志器

    Args:
        name: 日志器名称，通常使用 __name__

    Returns:
        配置好的日志器
    """
    if not _config_loaded:
        setup_logging()

    return logging.getLogger(name)
