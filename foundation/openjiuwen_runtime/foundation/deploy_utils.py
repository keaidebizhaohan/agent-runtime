"""部署工具函数"""
import os
from pathlib import Path
from .config import settings


def get_deploy_dir(deployment_id: str) -> Path:
    deploy_dir = Path(settings.DEPLOY_DIR).resolve() / deployment_id
    deploy_dir.mkdir(parents=True, exist_ok=True)
    return deploy_dir


def get_dist_dir() -> Path:
    dist_path = Path(settings.DIST_DIR).resolve()
    dist_path.mkdir(parents=True, exist_ok=True)
    return dist_path