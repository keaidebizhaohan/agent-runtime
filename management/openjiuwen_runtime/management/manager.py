import logging
import uuid
import asyncio
from datetime import datetime
from enum import Enum
from typing import Optional, Any
from urllib import request as urllib_request
from urllib import error as urllib_error

from openjiuwen_runtime.foundation.db.handler import DBHandler
from .models.enums import DeploymentType, DeploymentStatus
from .models.schemas import (
    DeploymentInfo,
    DeploymentCreate,
    DEPLOYMENT_TABLE_NAME,
    DeploymentFields,
)
from openjiuwen_runtime.foundation.db.table_def import TableDefinition, ColumnDefinition, IndexDefinition
from .deployments import (
    BaseDeploymentStrategy,
    ProcessInfo,
    DockerInfo,
    K8sInfo,
    SubprocessStrategy,
    DockerStrategy,
    K8sStrategy,
)

logger = logging.getLogger(__name__)


class DeployMode(str, Enum):
    """部署模式"""
    SUBPROCESS = "subprocess"
    DOCKER = "docker"
    K8S = "k8s"


DEPLOYMENT_TABLE_DEF = TableDefinition(
    table_name=DEPLOYMENT_TABLE_NAME,
    columns=[
        ColumnDefinition(DeploymentFields.ID, "integer", primary_key=True, autoincrement=True),
        ColumnDefinition(DeploymentFields.DEPLOYMENT_ID, "string", length=64, unique=True, nullable=False),
        ColumnDefinition(DeploymentFields.VERSION, "string", length=32, nullable=False),
        ColumnDefinition(DeploymentFields.DEPLOYMENT_TYPE, "string", length=32, nullable=False),
        ColumnDefinition(DeploymentFields.DEPLOYMENT_STATUS, "string", length=32, nullable=False),
        ColumnDefinition(DeploymentFields.NAME, "string", length=255, nullable=False),
        ColumnDefinition(DeploymentFields.URL, "string", length=512, nullable=True),
        ColumnDefinition(DeploymentFields.USER_ID, "string", length=64, nullable=True),
        ColumnDefinition(DeploymentFields.SPACE_ID, "string", length=64, nullable=True),
        ColumnDefinition(DeploymentFields.CREATED_AT, "datetime", nullable=False),
        ColumnDefinition(DeploymentFields.UPDATED_AT, "datetime", nullable=False),
        ColumnDefinition(DeploymentFields.DATA, "json", nullable=True),
    ],
    indexes=[
        IndexDefinition([DeploymentFields.DEPLOYMENT_ID], unique=True),
        IndexDefinition([DeploymentFields.USER_ID], unique=False),
        IndexDefinition([DeploymentFields.SPACE_ID], unique=False),
    ],
)


class DeploymentManager:
    """部署管理器"""

    def __init__(
            self,
            db_handler: DBHandler,
            strategies: Optional[dict[DeployMode, BaseDeploymentStrategy]] = None,
    ):
        self.db_handler = db_handler
        self._strategies = strategies or self._create_default_strategies()
        logger.debug("DeploymentManager initialized")

    def _create_default_strategies(self) -> dict[DeployMode, BaseDeploymentStrategy]:
        """创建默认策略"""
        return {
            DeployMode.SUBPROCESS: SubprocessStrategy(),
            DeployMode.DOCKER: DockerStrategy(),
            DeployMode.K8S: K8sStrategy(),
        }

    async def initialize(self) -> None:
        """初始化管理器"""
        logger.info("Initializing DeploymentManager")
        await self.db_handler.connect()
        await self.db_handler.init_table(DEPLOYMENT_TABLE_DEF)
        for strategy in self._strategies.values():
            await self.db_handler.init_table(strategy.get_table_definition())
        logger.info("DeploymentManager initialized successfully")

    async def shutdown(self) -> None:
        """关闭管理器"""
        logger.info("Shutting down DeploymentManager")
        await self.db_handler.disconnect()
        logger.info("DeploymentManager shutdown complete")

    def _generate_deployment_id(self) -> str:
        """生成部署ID"""
        return str(uuid.uuid4())

    def _get_strategy(self, mode: DeployMode) -> BaseDeploymentStrategy:
        """获取部署策略"""
        return self._strategies[mode]

    async def _detect_deploy_mode(self, deployment_id: str) -> Optional[DeployMode]:
        """检测部署模式"""
        logger.debug(f"Detecting deploy mode for deployment_id={deployment_id}")
        for mode, strategy in self._strategies.items():
            record = await strategy.get_record(self.db_handler, deployment_id)
            if record:
                logger.debug(f"Detected deploy mode: {mode} for deployment_id={deployment_id}")
                return mode
        logger.debug(f"No deploy mode found for deployment_id={deployment_id}")
        return None

    async def _check_health_endpoint(self, base_url: str, timeout_seconds: float = 2.0) -> bool:
        """检查部署服务 /health 是否可访问。"""
        url = base_url.rstrip("/") + "/health"

        def _probe() -> bool:
            req = urllib_request.Request(url, method="GET")
            with urllib_request.urlopen(req, timeout=timeout_seconds) as resp:
                return 200 <= resp.status < 300

        try:
            return await asyncio.to_thread(_probe)
        except (urllib_error.URLError, TimeoutError, OSError):
            return False

    async def _wait_until_deployment_ready(
        self,
        deployment_id: str,
        timeout_seconds: int = 600,
        interval_seconds: float = 20.0,
    ) -> None:
        """
        等待部署就绪：
        1) 状态为 running
        2) 若存在 URL，则 /health 探活成功
        """
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        last_status = None

        while asyncio.get_running_loop().time() < deadline:
            deployment = await self.get_deployment(deployment_id)
            if deployment is None:
                raise RuntimeError(f"Deployment {deployment_id} not found while waiting for readiness")

            last_status = deployment.deployment_status.value
            if deployment.deployment_status == DeploymentStatus.RUNNING:
                if deployment.url:
                    if await self._check_health_endpoint(deployment.url):
                        return
                else:
                    return

            if deployment.deployment_status == DeploymentStatus.FAILED:
                raise RuntimeError(f"Deployment {deployment_id} entered failed status")

            await asyncio.sleep(interval_seconds)

        raise RuntimeError(
            f"Deployment {deployment_id} not ready within {timeout_seconds}s (last_status={last_status})"
        )

    async def deploy_agent(
            self,
            name: str,
            version: str,
            mode: DeployMode = DeployMode.SUBPROCESS,
            user_id: Optional[str] = None,
            space_id: Optional[str] = None,
            **kwargs: Any,
    ) -> DeploymentInfo:
        """部署Agent"""
        logger.info(f"Deploying agent: name={name}, version={version}, mode={mode}, user_id={user_id}, space_id={space_id}")
        kwargs["package_name"] = name
        return await self._deploy(
            deployment_type=DeploymentType.AGENT,
            name=name,
            version=version,
            mode=mode,
            user_id=user_id,
            space_id=space_id,
            **kwargs,
        )

    async def deploy_plugin(
            self,
            name: str,
            version: str,
            mode: DeployMode = DeployMode.SUBPROCESS,
            url: Optional[str] = None,
            user_id: Optional[str] = None,
            space_id: Optional[str] = None,
            **kwargs: Any,
    ) -> DeploymentInfo:
        """部署Plugin"""
        logger.info(f"Deploying plugin: name={name}, version={version}, mode={mode}, user_id={user_id}, space_id={space_id}")
        return await self._deploy(
            deployment_type=DeploymentType.PLUGIN,
            name=name,
            version=version,
            mode=mode,
            url=url,
            user_id=user_id,
            space_id=space_id,
            **kwargs,
        )

    async def _deploy(
            self,
            deployment_type: DeploymentType,
            name: str,
            version: str,
            mode: DeployMode,
            user_id: Optional[str] = None,
            space_id: Optional[str] = None,
            **kwargs: Any,
    ) -> DeploymentInfo:
        """内部部署方法"""
        deployment_id = kwargs.pop("deployment_id", None) or self._generate_deployment_id()
        now = datetime.utcnow()

        logger.debug(f"deployment_id={deployment_id}, type={deployment_type}, name={name}")

        create_model = DeploymentCreate(
            deployment_id=deployment_id,
            version=version,
            deployment_type=deployment_type,
            name=name,
            url=kwargs.get("url"),
            user_id=user_id,
            space_id=space_id,
            data=kwargs.get("data"),
        )
        deployment_data = create_model.model_dump()
        deployment_data[DeploymentFields.DEPLOYMENT_STATUS] = DeploymentStatus.PENDING.value
        deployment_data[DeploymentFields.CREATED_AT] = now
        deployment_data[DeploymentFields.UPDATED_AT] = now
        
        await self.db_handler.create(DEPLOYMENT_TABLE_NAME, deployment_data)

        strategy = self._get_strategy(mode)

        try:
            await strategy.create_record(
                self.db_handler, deployment_id, version, **kwargs
            )
            await strategy.deploy(deployment_id, self.db_handler)

            await self._wait_until_deployment_ready(deployment_id)
            logger.info(f"Deployment completed: deployment_id={deployment_id}, name={name}")
        except Exception as e:
            logger.error(f"Deployment failed: deployment_id={deployment_id}, error={str(e)}")
            await self.db_handler.update(
                DEPLOYMENT_TABLE_NAME,
                {DeploymentFields.DEPLOYMENT_ID: deployment_id},
                {DeploymentFields.DEPLOYMENT_STATUS: DeploymentStatus.FAILED.value},
            )

        deployment_record = await self.db_handler.get(
            DEPLOYMENT_TABLE_NAME, 
            {DeploymentFields.DEPLOYMENT_ID: deployment_id}
        )
        return DeploymentInfo.model_validate(deployment_record)

    async def list_deployments(
            self,
            deployment_type: Optional[DeploymentType] = None,
            deployment_status: Optional[DeploymentStatus] = None,
            user_id: Optional[str] = None,
            space_id: Optional[str] = None,
            limit: int = 100,
            offset: int = 0,
    ) -> list[DeploymentInfo]:
        """列出部署"""
        logger.debug(
            f"Listing deployments: type={deployment_type}, status={deployment_status}, user_id={user_id}, space_id={space_id}, limit={limit}, offset={offset}")
        filters = {}
        if deployment_type:
            filters[DeploymentFields.DEPLOYMENT_TYPE] = deployment_type.value
        if deployment_status:
            filters[DeploymentFields.DEPLOYMENT_STATUS] = deployment_status.value
        if user_id:
            filters[DeploymentFields.USER_ID] = user_id
        if space_id:
            filters[DeploymentFields.SPACE_ID] = space_id

        records = await self.db_handler.list_records(
            DEPLOYMENT_TABLE_NAME, filters=filters if filters else None, limit=limit, offset=offset
        )
        result = [DeploymentInfo.model_validate(r if hasattr(r, "to_dict") else r) for r in records]
        logger.debug(f"Found {len(result)} deployments")
        return result

    async def get_deployment(self, deployment_id: str) -> Optional[DeploymentInfo]:
        """获取部署详情"""
        logger.debug(f"Getting deployment: deployment_id={deployment_id}")
        record = await self.db_handler.get(
            DEPLOYMENT_TABLE_NAME, 
            {DeploymentFields.DEPLOYMENT_ID: deployment_id}
        )
        if not record:
            logger.debug(f"Deployment not found: deployment_id={deployment_id}")
            return None
        if hasattr(record, "to_dict"):
            return DeploymentInfo.model_validate(record.to_dict())
        return DeploymentInfo.model_validate(record)

    async def get_deployment_status(self, deployment_id: str) -> Optional[DeploymentStatus]:
        """获取部署状态"""
        logger.debug(f"Getting deployment status: deployment_id={deployment_id}")
        record = await self.db_handler.get(
            DEPLOYMENT_TABLE_NAME, 
            {DeploymentFields.DEPLOYMENT_ID: deployment_id}
        )
        if not record:
            return None
        status = record.get(DeploymentFields.DEPLOYMENT_STATUS) if isinstance(record, dict) else record.deployment_status
        return DeploymentStatus(status)

    async def stop_deployment(
            self, deployment_id: str, mode: Optional[DeployMode] = None
    ) -> bool:
        """停止部署"""
        logger.info(f"Stopping deployment: deployment_id={deployment_id}")
        if mode is None:
            mode = await self._detect_deploy_mode(deployment_id)
            if mode is None:
                logger.warning(f"Cannot stop deployment, mode not found: deployment_id={deployment_id}")
                return False

        strategy = self._get_strategy(mode)
        result = await strategy.stop(deployment_id, self.db_handler)
        if result.success:
            logger.info(f"Deployment stopped: deployment_id={deployment_id}")
        else:
            logger.error(f"Failed to stop deployment: deployment_id={deployment_id}, message={result.message}")
        return result.success

    async def delete_deployment(
            self, deployment_id: str, mode: Optional[DeployMode] = None
    ) -> bool:
        """删除部署"""
        logger.info(f"Deleting deployment: deployment_id={deployment_id}")
        if mode is None:
            mode = await self._detect_deploy_mode(deployment_id)

        await self.stop_deployment(deployment_id, mode)

        if mode:
            strategy = self._get_strategy(mode)
            await strategy.delete_record(self.db_handler, deployment_id)

        result = await self.db_handler.delete(
            DEPLOYMENT_TABLE_NAME, 
            {DeploymentFields.DEPLOYMENT_ID: deployment_id}
        )
        if result:
            logger.info(f"Deployment deleted: deployment_id={deployment_id}")
        else:
            logger.error(f"Failed to delete deployment: deployment_id={deployment_id}")
        return result

    async def get_process_info(self, deployment_id: str) -> Optional[ProcessInfo]:
        """获取进程部署详情"""
        logger.debug(f"Getting process info: deployment_id={deployment_id}")
        strategy = self._get_strategy(DeployMode.SUBPROCESS)
        return await strategy.get_info(self.db_handler, deployment_id)

    async def get_docker_info(self, deployment_id: str) -> Optional[DockerInfo]:
        """获取Docker部署详情"""
        logger.debug(f"Getting docker info: deployment_id={deployment_id}")
        strategy = self._get_strategy(DeployMode.DOCKER)
        return await strategy.get_info(self.db_handler, deployment_id)

    async def get_k8s_info(self, deployment_id: str) -> Optional[K8sInfo]:
        """获取K8S部署详情"""
        logger.debug(f"Getting k8s info: deployment_id={deployment_id}")
        strategy = self._get_strategy(DeployMode.K8S)
        return await strategy.get_info(self.db_handler, deployment_id)
