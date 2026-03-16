"""本地进程部署器 (v2.0)

v2.0 特性:
- 为每个部署创建独立的虚拟环境
- 支持WHL包部署
- 使用 python -m package_name 方式运行
"""

import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any

from .base import Deployer
from ..models.enums import DeploymentStatus
from ..utils.venv_manager import VirtualEnvironmentManager

logger = logging.getLogger(__name__)


class LocalSubprocessDeployer(Deployer):
    """本地进程部署器 (v2.0)"""

    def __init__(self, venvs_root: str = "./venvs"):
        """
        初始化部署器

        Args:
            venvs_root: 虚拟环境根目录
        """
        self.venv_manager = VirtualEnvironmentManager(venvs_root)

    def _kill_by_pid(self, pid: int) -> bool:
        """通过 PID 终止进程（跨进程有效）"""
        try:
            if sys.platform == "win32":
                # Windows: 使用 taskkill
                cmd = f"taskkill /F /PID {pid}"
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True
                )
                success = result.returncode == 0
                if success:
                    logger.info(f"Killed process {pid}")
                else:
                    logger.warning(f"Failed to kill process {pid}: {result.stderr}")
                return success
            else:
                # Linux/Mac: 使用 kill
                result = subprocess.run(
                    ["kill", "-9", str(pid)],
                    capture_output=True,
                    text=True
                )
                success = result.returncode == 0
                if success:
                    logger.info(f"Killed process {pid}")
                else:
                    logger.warning(f"Failed to kill process {pid}")
                return success
        except Exception as e:
            logger.error(f"Error killing process {pid}: {e}")
            return False

    async def deploy(
        self,
        whl_path: str,
        name: str,
        deployment_id: str,
        port: int,
        host: str = "127.0.0.1",
        **kwargs
    ) -> Dict[str, Any]:
        """
        使用WHL包部署应用

        流程:
        1. 创建独立虚拟环境
        2. 在虚拟环境中安装WHL包
        3. 使用 python -m name 启动应用

        Args:
            whl_path: WHL包文件路径（由 Manager SDK 内部打包生成）
            name: 部署名称=包名，用于 python -m 运行
            deployment_id: 部署唯一标识
            port: 服务端口
            host: 服务主机
            **kwargs: 其他部署参数

        Returns:
            部署信息字典
        """
        logger.info(f"Deploying {deployment_id} from WHL {whl_path} on {host}:{port}")

        venv_path = None
        try:
            # 1. 创建虚拟环境
            venv_path = self.venv_manager.create_venv(deployment_id)
            logger.info(f"Virtual environment created: {venv_path}")

            # 2. 安装WHL包
            self.venv_manager.install_whl(deployment_id, whl_path)
            logger.info(f"WHL package installed: {whl_path}")

            # 3. 获取虚拟环境Python解释器
            python_executable = self.venv_manager.get_python_executable(deployment_id)

            # 4. 构建启动命令: python -m name --host --port
            cmd = [
                str(python_executable),
                "-m",
                name,
                "--host", host,
                "--port", str(port)
            ]
            logger.debug(f"Command: {' '.join(cmd)}")

            # 5. 启动进程 (Windows: 使用新进程组，避免Ctrl+C影响子进程)
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )

            # 6. 等待进程启动并检查状态
            await asyncio.sleep(2)

            if process.poll() is not None:
                # 进程已经退出，读取错误信息
                stderr = process.stderr.read()
                stdout = process.stdout.read()
                error_msg = stderr or stdout or "Unknown error"
                logger.error(f"Process exited for {deployment_id}: {error_msg}")
                raise RuntimeError(f"Process exited: {error_msg}")

            logger.info(f"Deployment {deployment_id} succeeded, PID: {process.pid}")
            return {
                "deployment_id": deployment_id,
                "url": f"http://{host}:{port}",
                "status": DeploymentStatus.RUNNING,
                "pid": process.pid,
                "venv_path": str(venv_path),
            }
        except Exception as e:
            logger.error(f"Deployment {deployment_id} failed: {e}")
            # 清理虚拟环境
            if venv_path:
                self.venv_manager.delete_venv(deployment_id)
            raise RuntimeError(f"Failed to deploy: {e}")

    async def stop(self, deployment: dict) -> bool:
        """
        停止部署并清理虚拟环境

        Args:
            deployment: 部署信息字典
        """
        deployment_id = deployment.get("deployment_id")
        pid = deployment.get("pid")
        logger.info(f"Stopping deployment {deployment_id}, PID: {pid}")

        # 1. 终止进程
        success = False
        if pid:
            success = self._kill_by_pid(pid)
            if success:
                logger.info(f"Deployment {deployment_id} process stopped")
            else:
                logger.warning(f"Failed to kill process {pid}")

        # 2. 清理虚拟环境
        if deployment.get("venv_path"):
            venv_deleted = self.venv_manager.delete_venv(deployment_id)
            if venv_deleted:
                logger.info(f"Virtual environment deleted: {deployment_id}")

        return success

    async def get_status(self, deployment: dict) -> DeploymentStatus:
        """获取部署状态"""
        deployment_id = deployment.get("deployment_id")
        pid = deployment.get("pid")
        if not pid:
            logger.debug(f"Deployment {deployment_id} has no PID, status: STOPPED")
            return DeploymentStatus.STOPPED

        # 通过 PID 检查进程是否运行
        if sys.platform == "win32":
            # Windows: 使用 tasklist 检查
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True
            )
            is_running = str(pid) in result.stdout
            status = DeploymentStatus.RUNNING if is_running else DeploymentStatus.STOPPED
            logger.info(f"Deployment {deployment_id} PID {pid} status: {status}")
            return status
        else:
            # Linux/Mac: 使用 kill -0 检查
            result = subprocess.run(
                ["kill", "-0", str(pid)],
                capture_output=True
            )
            is_running = result.returncode == 0
            status = DeploymentStatus.RUNNING if is_running else DeploymentStatus.STOPPED
            logger.info(f"Deployment {deployment_id} PID {pid} status: {status}")
            return status
