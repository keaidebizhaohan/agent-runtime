"""Docker 部署器

特性:
- 使用 Docker 容器部署应用
- 支持 WHL 包部署
- 支持环境变量和卷挂载
- 支持容器生命周期管理
"""

import asyncio
import logging
import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional

from ..base.deployer import Deployer
from ..base.models import DeployContext, DeployResult
from .models import DockerParams
from ...models.enums import DeploymentStatus

from openjiuwen_runtime.foundation.config import settings

logger = logging.getLogger(__name__)


class DockerDeployer(Deployer[DockerParams]):
    """Docker 部署器"""

    def __init__(
            self,
            default_host: str = "localhost",
            docker_host: Optional[str] = None,
    ):
        self.default_host = default_host
        self.docker_host = docker_host
        self._containers: dict[str, str] = {}
        logger.debug(f"DockerDeployer initialized: docker_host={docker_host}")

    def _build_docker_command(self, *args: str) -> list[str]:
        """构建 Docker 命令"""
        cmd = ["docker"]
        if self.docker_host:
            cmd.extend(["-H", self.docker_host])
        cmd.extend(args)
        return cmd

    async def _run_docker_command(self, *args: str) -> tuple[bool, str]:
        """运行 Docker 命令"""
        cmd = self._build_docker_command(*args)

        logger.debug(f"Running docker command: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            return True, stdout.decode().strip()
        return False, stderr.decode().strip()


    async def deploy_lowcode_container(
        self,
        container_name: str,
        env_vars: dict,
        volumes: list,
        port: str,
        ir_source_path: str
    ) -> str:
        """
        创建低代码Agent容器：采用 docker create → docker cp → docker start 流程。

        规避问题：
            禁止使用 docker run -v 挂载容器内文件。
            因如果当前服务运行于容器中，需要挂载/var/run/docker.sock，
            所有挂载路径均指向宿主机，直接挂载容器内文件会导致目标文件被创建为空目录。
        """
        # 创建容器（不启动）
        create_args = ["create", "--name", container_name]

        # 环境变量
        if env_vars:
            for k, v in env_vars.items():
                create_args.extend(["-e", f"{k}={v}"])

        # 挂载卷
        if volumes:
            for vol in volumes:
                if "source" in vol and "target" in vol:
                    create_args.extend(["-v", f"{vol['source']}:{vol['target']}"])

        create_args.extend(["-p", port])

        # 镜像
        image_name = settings.LOWCODE_IMAGE
        if not image_name:
            raise RuntimeError("Environment variable LOWCODE_IMAGE is not set")
        create_args.append(image_name)

        logger.debug(f"Creating lowcode agent container: {container_name}")
        success, output = await self._run_docker_command(*create_args)
        if not success:
            raise RuntimeError(f"create lowcode container failed: {output}")

        container_id = output.strip()
        logger.debug(f"container created: {container_id}")

        # 复制 ir.json 到容器
        target_path = f"{container_name}:/app/ir.json"
        logger.debug(f"docker cp {ir_source_path} -> {target_path}")
        success, cp_out = await self._run_docker_command("cp", ir_source_path, target_path)
        if not success:
            raise RuntimeError(f"docker cp failed: {cp_out}")

        # 启动容器
        logger.debug(f"Start container: {container_name}")
        success, start_out = await self._run_docker_command("start", container_id)
        if not success:
            raise RuntimeError(f"Start container failed: {start_out}")

        return container_id

    async def deploy(self, ctx: DeployContext[DockerParams]) -> DeployResult:
        """使用 Docker 容器部署应用
        Args:
            ctx: 部署上下文参数

        Returns:
            DeployResult: 部署结果
        """
        deployment_id = ctx.deployment_id
        logger.info(f"Deploying docker: deployment_id={deployment_id}, host={ctx.host}")

        try:
            docker_params = ctx.params or DockerParams()
            whl_path = docker_params.whl_path
            ir_path = docker_params.ir_path
            package_name = docker_params.package_name
            container_name = docker_params.container_name or f"deploy_{deployment_id}"
            env_vars = docker_params.env_vars
            volumes = docker_params.volumes
            host = ctx.host or self.default_host
            iport = "8090"

            import json
            logger.debug(f"docker_params 完整内容: \n{json.dumps(docker_params.__dict__, indent=2, ensure_ascii=False)}")

            # 非低码情况
            if not ir_path:
                if not whl_path:
                    raise RuntimeError("whl_path is required for docker deployment")
                if not package_name:
                    raise RuntimeError("package_name is required for docker deployment")

            # 创建并启动低代码Agent容器
            container_id = await self.deploy_lowcode_container(
                container_name=container_name,
                env_vars=env_vars,
                volumes=volumes,
                port=iport,
                ir_source_path=ir_path
            )
            self._containers[deployment_id] = container_id

            # 获取该容器在宿主机上的port
            success, port_output = await self._run_docker_command("port", container_id, iport)
            if not success or not port_output:
                raise RuntimeError(f"无法获取容器映射的端口: {container_id}")

            # 解析输出 0.0.0.0:12345 → 拿到 12345
            port = port_output.strip().split(":")[-1]
            url = f"http://{settings.IP}:{port}"

            logger.info(f"Docker deployed: deployment_id={deployment_id}, container={container_name}, url={url}")
            return DeployResult(
                success=True,
                deployment_id=deployment_id,
                message="Docker deployment started successfully",
                url=url,
            )

        except Exception as e:
            logger.error(f"Docker deploy failed: deployment_id={deployment_id}, error={str(e)}")
            return DeployResult(
                success=False,
                deployment_id=deployment_id,
                message=f"Deployment failed: {str(e)}"
            )

    async def stop(self, deployment_id: str, **kwargs) -> DeployResult:
        """停止并删除 Docker 容器

        Args:
            deployment_id: 部署ID
            **kwargs: container_name (容器名称)

        Returns:
            DeployResult: 停止结果
        """
        container_name = kwargs.get("container_name") or f"deploy_{deployment_id}"
        logger.info(f"Stopping docker: deployment_id={deployment_id}, container_name={container_name}")

        try:
            # 停止容器
            logger.debug(f"Stopping container: container_name={container_name}")
            success, output = await self._run_docker_command("stop", container_name)
            if not success:
                logger.warning(f"Docker stop failed: deployment_id={deployment_id}, error={output}")

            # 删除容器
            success, output = await self._run_docker_command("rm", container_name)
            if not success:
                logger.warning(f"Docker rm failed: deployment_id={deployment_id}, error={output}")

            # 删除镜像
            # image_name = f"{deployment_id}:latest"
            # success, output = await self._run_docker_command("rmi", image_name)
            # if not success:
            #    logger.warning(f"Docker rmi failed: deployment_id={deployment_id}, error={output}")

            if deployment_id in self._containers:
                del self._containers[deployment_id]

            # 清理部署目录
            deploy_context_dir = settings.deploy_path/deployment_id
            logger.debug(f"Cleaning deploy directory: {deploy_context_dir}")
            shutil.rmtree(deploy_context_dir, ignore_errors=True)

            logger.info(f"Docker stopped: deployment_id={deployment_id}")
            return DeployResult(
                success=True,
                deployment_id=deployment_id,
                message="Docker deployment stopped successfully"
            )

        except Exception as e:
            logger.error(f"Docker stop failed: deployment_id={deployment_id}, error={str(e)}")
            return DeployResult(
                success=False,
                deployment_id=deployment_id,
                message=f"Stop failed: {str(e)}"
            )

        except Exception as e:
            logger.error(f"Docker stop failed: deployment_id={deployment_id}, error={str(e)}")
            return DeployResult(
                success=False,
                deployment_id=deployment_id,
                message=f"Stop failed: {str(e)}"
            )

    async def get_status(self, deployment_id: str, **kwargs) -> DeploymentStatus:
        """获取 Docker 容器状态

        Args:
            deployment_id: 部署ID
            **kwargs: container_name (容器名称)

        Returns:
            DeploymentStatus: 部署状态
        """
        container_name = kwargs.get("container_name") or f"deploy_{deployment_id}"
        logger.debug(f"Getting docker status: deployment_id={deployment_id}, container_name={container_name}")

        success, output = await self._run_docker_command(
            "inspect", "-f", "{{.State.Status}}", container_name
        )

        if not success:
            return DeploymentStatus.STOPPED

        if output == "running":
            return DeploymentStatus.RUNNING
        else:
            return DeploymentStatus.STOPPED
