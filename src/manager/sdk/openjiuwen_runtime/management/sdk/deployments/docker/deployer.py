import asyncio
import logging
from typing import Optional

from ..base.deployer import Deployer
from ..base.models import DeployContext, DeployResult
from .models import DockerParams
from ...models.enums import DeploymentStatus

logger = logging.getLogger(__name__)


class DockerDeployer(Deployer[DockerParams]):
    def __init__(
            self,
            default_host: str = "localhost",
            docker_host: Optional[str] = None,
    ):
        self.default_host = default_host
        self.docker_host = docker_host
        self._containers: dict[str, str] = {}
        logger.debug(f"DockerDeployer initialized: docker_host={docker_host}")

    async def _run_docker_command(self, *args: str) -> tuple[bool, str]:
        cmd = ["docker"]
        if self.docker_host:
            cmd.extend(["-H", self.docker_host])
        cmd.extend(args)

        logger.debug(f"Running docker command: {' '.join(args)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            return True, stdout.decode().strip()
        return False, stderr.decode().strip()

    async def deploy(self, ctx: DeployContext[DockerParams]) -> DeployResult:
        logger.info(f"Deploying docker: deployment_id={ctx.deployment_id}, host={ctx.host}")
        try:
            docker_params = ctx.params or DockerParams()
            image = docker_params.image
            container_name = docker_params.container_name or f"deploy_{ctx.deployment_id}"
            env_vars = docker_params.env_vars
            volumes = docker_params.volumes
            host = ctx.host or self.default_host

            image_name = image or f"{ctx.deployment_id}:latest"

            if image:
                logger.debug(f"Using existing image: image_name={image_name}")
            else:
                logger.debug(f"Building docker image: image_name={image_name}")
                success, output = await self._run_docker_command(
                    "build", "-t", image_name, "."
                )
                if not success:
                    logger.error(f"Docker build failed: deployment_id={ctx.deployment_id}, error={output}")
                    return DeployResult(
                        success=False, message=f"Docker build failed: {output}"
                    )

            run_args = ["run", "-d", "--name", container_name]

            if env_vars:
                for key, value in env_vars.items():
                    run_args.extend(["-e", f"{key}={value}"])

            if volumes:
                for vol in volumes:
                    if "source" in vol and "target" in vol:
                        run_args.extend(["-v", f"{vol['source']}:{vol['target']}"])

            run_args.extend(["-p", "8000:8000", image_name])

            logger.debug(f"Running docker container: container_name={container_name}, image={image_name}")
            success, output = await self._run_docker_command(*run_args)

            if not success:
                logger.error(f"Docker run failed: deployment_id={ctx.deployment_id}, error={output}")
                return DeployResult(
                    success=False, message=f"Docker run failed: {output}"
                )

            container_id = output
            self._containers[ctx.deployment_id] = container_id

            url = f"http://{host}:8000"

            logger.info(f"Docker deployed: deployment_id={ctx.deployment_id}, container={container_name}, url={url}")
            return DeployResult(
                success=True,
                message="Docker deployment started successfully",
                url=url,
            )

        except Exception as e:
            logger.error(f"Docker deploy failed: deployment_id={ctx.deployment_id}, error={str(e)}")
            return DeployResult(success=False, message=f"Deployment failed: {str(e)}")

    async def stop(self, deployment_id: str, **kwargs) -> DeployResult:
        logger.info(f"Stopping docker: deployment_id={deployment_id}")
        try:
            container_name = f"deploy_{deployment_id}"

            logger.debug(f"Stopping container: container_name={container_name}")
            success, output = await self._run_docker_command("stop", container_name)
            if not success:
                logger.error(f"Docker stop failed: deployment_id={deployment_id}, error={output}")
                return DeployResult(success=False, message=f"Docker stop failed: {output}")

            success, output = await self._run_docker_command("rm", container_name)

            if deployment_id in self._containers:
                del self._containers[deployment_id]

            logger.info(f"Docker stopped: deployment_id={deployment_id}")
            return DeployResult(success=True, message="Docker deployment stopped successfully")

        except Exception as e:
            logger.error(f"Docker stop failed: deployment_id={deployment_id}, error={str(e)}")
            return DeployResult(success=False, message=f"Stop failed: {str(e)}")

    async def get_status(self, deployment_id: str, **kwargs) -> DeploymentStatus:
        logger.debug(f"Getting docker status: deployment_id={deployment_id}")
        container_name = f"deploy_{deployment_id}"
        success, output = await self._run_docker_command(
            "inspect", "-f", "{{.State.Status}}", container_name
        )

        if not success:
            return DeploymentStatus.STOPPED

        if output == "running":
            return DeploymentStatus.RUNNING
        else:
            return DeploymentStatus.STOPPED
