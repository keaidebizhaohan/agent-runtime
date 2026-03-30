"""部署工具函数"""
import os
from pathlib import Path

DEPLOY_ROOT_DEFAULT_DIR = str((Path(__file__).parents[3] / ".deploys").resolve())
DIST_DEFAULT_DIR = str((Path(__file__).parents[3] / "dist").resolve())


def get_deploy_dir(deployment_id: str) -> Path:
    DEPLOY_ROOT_DIR = os.getenv("DEPLOY_DIR", DEPLOY_ROOT_DEFAULT_DIR)
    deploy_dir = Path(DEPLOY_ROOT_DIR).resolve() / deployment_id
    deploy_dir.mkdir(parents=True, exist_ok=True)
    return deploy_dir


def get_dist_dir() -> Path:
    DIST_DIR = os.getenv("DIST_DIR", DIST_DEFAULT_DIR)
    dist_path = Path(DIST_DIR).resolve()
    dist_path.mkdir(parents=True, exist_ok=True)
    return dist_path