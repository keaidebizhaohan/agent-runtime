import logging
import logging.config
import os
from pathlib import Path
from typing import Optional

import yaml

_config_loaded: bool = False


def get_config_path() -> Path:
    """获取日志配置文件路径"""
    current_dir = Path(__file__).parent
    return current_dir.parent / "config" / "logging.yaml"


def setup_logging(config_path: Optional[str] = None) -> None:
    """
    初始化日志配置
    
    Args:
        config_path: 日志配置文件路径，默认使用内置配置
    """
    global _config_loaded

    if _config_loaded:
        return

    if config_path is None:
        config_path = str(get_config_path())

    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            logging.config.dictConfig(config)
    else:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(funcName)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

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
