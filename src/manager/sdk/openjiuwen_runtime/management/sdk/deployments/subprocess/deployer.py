"""本地进程部署器

特性:
- 为每个部署创建独立的虚拟环境
- 支持WHL包部署
- 使用 python -m package_name 方式运行
- 支持跨进程管理（通过PID）
"""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from typing import Dict, Optional

from ..base.deployer import Deployer
from ..base.models import DeployContext, DeployResult
from .models import SubprocessParams
from ...foundation.venv_manager import VirtualEnvironmentManager
from ...models.enums import DeploymentStatus

logger = logging.getLogger(__name__)


class LocalSubprocessDeployer(Deployer[SubprocessParams]):
    """本地进程部署器"""

    def __init__(
            self,
            default_host: str = "127.0.0.1",
            default_port_start: int = 8000,
            venv_base_path: str = "./venvs",
    ):
        self.default_host = default_host
        self.default_port_start = default_port_start
        self.venv_base_path = venv_base_path
        self.venv_manager = VirtualEnvironmentManager(venv_base_path)
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
        logger.debug(f"LocalSubprocessDeployer initialized: venv_base_path={venv_base_path}")

    def _kill_by_pid(self, pid: int) -> bool:
        """通过 PID 终止进程（跨进程有效）"""
        try:
            if sys.platform == "win32":
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

    def _check_process_by_pid(self, pid: int) -> bool:
        """通过 PID 检查进程是否运行"""
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True
            )
            return str(pid) in result.stdout
        else:
            result = subprocess.run(
                ["kill", "-0", str(pid)],
                capture_output=True
            )
            return result.returncode == 0

    def _get_venv_python_path(self, venv_path: str) -> str:
        """获取虚拟环境中的 Python 可执行文件路径"""
        if os.name == "nt":
            return os.path.join(venv_path, "Scripts", "python.exe")
        return os.path.join(venv_path, "bin", "python")

    def _get_venv_pip_path(self, venv_path: str) -> str:
        """获取虚拟环境中的 pip 可执行文件路径"""
        if os.name == "nt":
            return os.path.join(venv_path, "Scripts", "pip.exe")
        return os.path.join(venv_path, "bin", "pip")

    async def deploy(self, ctx: DeployContext[SubprocessParams]) -> DeployResult:
        """使用WHL包部署应用

        流程:
        1. 创建独立虚拟环境
        2. 在虚拟环境中安装WHL包
        3. 使用 python -m name 启动应用

        Args:
            ctx: 部署上下文参数

        Returns:
            DeployResult: 部署结果
        """
        deployment_id = ctx.deployment_id
        logger.info(f"Deploying subprocess: deployment_id={ctx.deployment_id}, host={ctx.host}")
        try:
            subprocess_params = ctx.params or SubprocessParams()
            whl_path = subprocess_params.whl_path
            package_name = subprocess_params.package_name
            # venv_path = subprocess_params.venv_path or os.path.join(
            #     self.venv_base_path, ctx.deployment_id
            # )

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
                package_name,
                "--host", ctx.host,
                "--port", str(ctx.port)
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

            return DeployResult(
                success=True,
                deployment_id=deployment_id,
                message="Deployment started successfully",
                url=ctx.url,
            )

        except Exception as e:
            logger.error(f"Subprocess deploy failed: deployment_id={ctx.deployment_id}, error={str(e)}")
            return DeployResult(success=False,
                                deployment_id=deployment_id, message=f"Deployment failed: {str(e)}")

    async def stop(self, deployment_id: str, **kwargs) -> DeployResult:
        """停止部署并清理虚拟环境

        Args:
            deployment_id: 部署ID
            **kwargs: pid (进程PID), venv_path (虚拟环境路径)

        Returns:
            DeployResult: 停止结果
        """
        pid = kwargs.get("pid")
        venv_path = kwargs.get("venv_path")
        logger.info(f"Stopping subprocess: deployment_id={deployment_id}, pid={pid}")
        try:
            if deployment_id in self._processes:
                process = self._processes[deployment_id]
                logger.debug(f"Terminating process: deployment_id={deployment_id}, pid={process.pid}")
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=10)
                except asyncio.TimeoutError:
                    logger.warning(f"Process did not terminate gracefully, killing: deployment_id={deployment_id}")
                    process.kill()
                del self._processes[deployment_id]
            elif pid:
                success = self._kill_by_pid(pid)
                if not success:
                    logger.warning(f"Failed to kill process by pid: {pid}")

            if venv_path and os.path.exists(venv_path):
                logger.debug(f"Deleting virtual environment: {venv_path}")
                shutil.rmtree(venv_path, ignore_errors=True)

            logger.info(f"Subprocess stopped: deployment_id={deployment_id}")
            return DeployResult(success=True, message="Deployment stopped successfully")

        except Exception as e:
            logger.error(f"Subprocess stop failed: deployment_id={deployment_id}, error={str(e)}")
            return DeployResult(success=False, message=f"Stop failed: {str(e)}")

    async def get_status(self, deployment_id: str, **kwargs) -> DeploymentStatus:
        """获取部署状态

        Args:
            deployment_id: 部署ID
            **kwargs: pid (进程PID)

        Returns:
            DeploymentStatus: 部署状态
        """
        pid = kwargs.get("pid")
        logger.debug(f"Getting subprocess status: deployment_id={deployment_id}, pid={pid}")

        if deployment_id in self._processes:
            process = self._processes[deployment_id]
            if process.returncode is None:
                return DeploymentStatus.RUNNING
            else:
                return DeploymentStatus.STOPPED

        if pid:
            is_running = self._check_process_by_pid(pid)
            return DeploymentStatus.RUNNING if is_running else DeploymentStatus.STOPPED

        return DeploymentStatus.PENDING

    def _get_available_port(self) -> int:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            s.listen(1)
            port = s.getsockname()[1]
        return port
