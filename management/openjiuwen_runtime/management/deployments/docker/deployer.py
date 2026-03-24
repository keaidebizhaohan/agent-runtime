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
from pathlib import Path
from typing import Optional

from ..base.deployer import Deployer
from ..base.models import DeployContext, DeployResult
from .models import DockerParams
from ...models.enums import DeploymentStatus

logger = logging.getLogger(__name__)


class DockerDeployer(Deployer[DockerParams]):
    """Docker 部署器"""

    def __init__(
            self,
            default_host: str = "localhost",
            docker_host: Optional[str] = None,
            deploy_dir: Optional[str] = None,
    ):
        self.default_host = default_host
        self.docker_host = docker_host
        self.deploy_dir = Path(deploy_dir or os.getenv("DEPLOY_DIR", "./.deploys")).resolve()
        self.deploy_dir.mkdir(parents=True, exist_ok=True)
        self._containers: dict[str, str] = {}
        logger.debug(f"DockerDeployer initialized: docker_host={docker_host}, deploy_dir={self.deploy_dir}")

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

    def _generate_dockerfile(self, whl_path: str, package_name: str, port: str) -> str:
        """生成 Dockerfile"""
        whl_name = Path(whl_path).name
        base_image =os.getenv("BASE_IMAGE", "swr.cn-north-4.myhuaweicloud.com/openjiuwen/studio-python-tool-amd64:0.1.0")
        logger.debug(f"whl_name: {whl_name}")

        return f"""ARG BASE_IMAGE
FROM {base_image}

ARG WHL_FILE="{whl_name}"
ARG PACKAGE_NAME="{package_name}"

RUN mkdir -p /app/dist
RUN useradd --create-home --shell /bin/bash app
RUN chown -R app:app /app

USER app
# Copy Python packages from builder stage
COPY {whl_name} /app/dist
RUN pip3 install /app/dist/{whl_name} --target=/app/site-packages --retries=5 --timeout=120

ENV PYTHONPATH=/app/site-packages
ENV PACKAGE_NAME={package_name}

WORKDIR /app

# Start the application
CMD python -m {package_name} --host 0.0.0.0 --port {port}
"""

    async def deploy(self, ctx: DeployContext[DockerParams]) -> DeployResult:
        """使用 Docker 容器部署应用

        流程:
        1. 生成 Dockerfile
        2. 构建 Docker 镜像
        3. 运行 Docker 容器

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
            package_name = docker_params.package_name
            container_name = docker_params.container_name or f"deploy_{deployment_id}"
            env_vars = docker_params.env_vars
            volumes = docker_params.volumes
            host = ctx.host or self.default_host
            iport = "8090"

            if not whl_path:
                raise RuntimeError("whl_path is required for docker deployment")
            if not package_name:
                raise RuntimeError("package_name is required for docker deployment")

            # 1. 生成 Dockerfile
            dockerfile_content = self._generate_dockerfile(whl_path, package_name, iport)

            # 使用指定目录：DEPLOY_DIR/deployment_id/
            deploy_context_dir = self.deploy_dir / deployment_id
            deploy_context_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Using deploy context directory: {deploy_context_dir}")

            dockerfile_path = deploy_context_dir / "Dockerfile"
            dockerfile_path.write_text(dockerfile_content)

            # 复制 WHL 文件到部署目录
            whl_file = Path(whl_path)
            if whl_file.exists():
                import shutil
                shutil.copy(whl_path, deploy_context_dir)
            else:
                raise RuntimeError(f"WHL file not found: {whl_path}")

            # 2. 构建 Docker 镜像
            image_name = f"{deployment_id}:latest"
            logger.debug(f"Building docker image: image_name={image_name}")

            success, output = await self._run_docker_command(
                "build", "-t", image_name, str(deploy_context_dir)
            )

            if not success:
                logger.error(f"Docker build failed: deployment_id={deployment_id}, error={output}")
                return DeployResult(
                    success=False,
                    deployment_id=deployment_id,
                    message=f"Docker build failed: {output}"
                )

            # 3. 运行 Docker 容器
            run_args = ["run", "-d", "--name", container_name]

            if env_vars:
                for key, value in env_vars.items():
                    run_args.extend(["-e", f"{key}={value}"])

            if volumes:
                for vol in volumes:
                    if "source" in vol and "target" in vol:
                        run_args.extend(["-v", f"{vol['source']}:{vol['target']}"])

            run_args.extend(["-p", iport, image_name])

            logger.debug(f"Running docker container: container_name={container_name}, image={image_name}")
            success, output = await self._run_docker_command(*run_args)

            if not success:
                logger.error(f"Docker run failed: deployment_id={deployment_id}, error={output}")
                return DeployResult(
                    success=False,
                    deployment_id=deployment_id,
                    message=f"Docker run failed: {output}"
                )

            container_id = output
            self._containers[deployment_id] = container_id

            # 获取该容器在宿主机上的port
            success, port_output = await self._run_docker_command("port", container_id, iport)
            if not success or not port_output:
                raise RuntimeError(f"无法获取容器映射的端口: {container_id}")

            # 解析输出 0.0.0.0:12345 → 拿到 12345
            port = port_output.strip().split(":")[-1]
            ip=os.getenv("IP", "localhost")
            url = f"http://{ip}:{port}"

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
            image_name = f"{deployment_id}:latest"
            success, output = await self._run_docker_command("rmi", image_name)
            if not success:
                logger.warning(f"Docker rmi failed: deployment_id={deployment_id}, error={output}")

            if deployment_id in self._containers:
                del self._containers[deployment_id]

            # 清理部署目录
            deploy_context_dir = self.deploy_dir / deployment_id
            if deploy_context_dir.exists():
                import shutil
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
