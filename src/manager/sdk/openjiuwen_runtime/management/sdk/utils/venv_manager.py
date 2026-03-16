"""虚拟环境管理器"""

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class VirtualEnvironmentManager:
    """
    虚拟环境管理器

    负责为每个部署创建、管理和清理独立的虚拟环境。
    """

    def __init__(self, venvs_root: str = "./venvs"):
        """
        初始化虚拟环境管理器

        Args:
            venvs_root: 虚拟环境根目录路径
        """
        self.venvs_root = Path(venvs_root)
        self.venvs_root.mkdir(parents=True, exist_ok=True)
        logger.info(f"VirtualEnvironmentManager initialized with root: {self.venvs_root}")

    def create_venv(self, deployment_id: str) -> Path:
        """
        为部署创建独立的虚拟环境

        Args:
            deployment_id: 部署ID，用作虚拟环境目录名

        Returns:
            虚拟环境路径

        Raises:
            RuntimeError: 虚拟环境创建失败
        """
        venv_path = self.venvs_root / deployment_id

        if venv_path.exists():
            logger.info(f"Virtual environment already exists: {venv_path}")
            return venv_path

        logger.info(f"Creating virtual environment: {venv_path}")

        try:
            # 使用python -m venv创建虚拟环境
            subprocess.run(
                [sys.executable, "-m", "venv", str(venv_path)],
                check=True,
                capture_output=True,
                text=True
            )
            logger.info(f"Virtual environment created successfully: {venv_path}")
            return venv_path
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create virtual environment: {e.stderr}")
            raise RuntimeError(f"Failed to create venv: {e}")

    def get_python_executable(self, deployment_id: str) -> Path:
        """
        获取虚拟环境中的Python可执行文件路径

        Args:
            deployment_id: 部署ID

        Returns:
            Python可执行文件路径

        Raises:
            RuntimeError: Python可执行文件未找到
        """
        venv_path = self.venvs_root / deployment_id

        if not venv_path.exists():
            raise RuntimeError(f"Virtual environment not found: {venv_path}")

        if sys.platform == "win32":
            # Windows: Scripts/python.exe
            python_path = venv_path / "Scripts" / "python.exe"
        else:
            # Linux/Mac: bin/python
            python_path = venv_path / "bin" / "python"

        if not python_path.exists():
            raise RuntimeError(f"Python executable not found: {python_path}")

        return python_path

    def install_whl(self, deployment_id: str, whl_path: str) -> bool:
        """
        在虚拟环境中安装WHL包

        Args:
            deployment_id: 部署ID
            whl_path: WHL包文件路径

        Returns:
            是否安装成功

        Raises:
            RuntimeError: 安装失败
        """
        python_executable = self.get_python_executable(deployment_id)

        logger.info(f"Installing WHL package: {whl_path} into {deployment_id}")

        try:
            # 使用虚拟环境的pip安装WHL包
            subprocess.run(
                [
                    str(python_executable), "-m", "pip", "install",
                    whl_path
                ],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"WHL package installed successfully: {whl_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install WHL: {e.stderr}")
            raise RuntimeError(f"Failed to install WHL package: {e}")

    def delete_venv(self, deployment_id: str) -> bool:
        """
        删除部署的虚拟环境

        Args:
            deployment_id: 部署ID

        Returns:
            是否删除成功
        """
        venv_path = self.venvs_root / deployment_id

        if not venv_path.exists():
            logger.warning(f"Virtual environment not found: {venv_path}")
            return False

        logger.info(f"Deleting virtual environment: {venv_path}")

        try:
            shutil.rmtree(venv_path)
            logger.info(f"Virtual environment deleted: {venv_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete virtual environment: {e}")
            return False

    def venv_exists(self, deployment_id: str) -> bool:
        """
        检查虚拟环境是否存在

        Args:
            deployment_id: 部署ID

        Returns:
            虚拟环境是否存在
        """
        venv_path = self.venvs_root / deployment_id
        return venv_path.exists()
