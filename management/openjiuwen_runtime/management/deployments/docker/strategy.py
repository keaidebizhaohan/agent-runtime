from datetime import datetime
from typing import Any, Optional

from ..base.strategy import BaseDeploymentStrategy
from ..base.models import DeployContext, CommonParams
from .models import DockerParams, DockerInfo, DockerCreate, DOCKER_TABLE_DEF
from .deployer import DockerDeployer


class DockerStrategy(BaseDeploymentStrategy[DockerInfo]):
    def _create_default_deployer(self) -> Any:
        return DockerDeployer()

    def _create_table_definition(self):
        return DOCKER_TABLE_DEF

    def _get_info_class(self) -> type:
        return DockerInfo

    def _build_deploy_context(self, record: Any, deployment: Any) -> DeployContext[DockerParams]:
        if hasattr(record, "to_dict"):
            record_dict = record.to_dict()
        else:
            record_dict = record

        common = CommonParams(
            deployment_id=record_dict["deployment_id"],
            host=record_dict["host"],
            url=record_dict.get("url"),
        )

        docker_params = DockerParams()
        if record_dict.get("data"):
            data = record_dict["data"]
            docker_params = DockerParams(
                image=data.get("image"),
                container_name=data.get("container_name"),
                env_vars=data.get("env_vars"),
                volumes=data.get("volumes"),
            )

        return DeployContext(common=common, params=docker_params, data=record_dict.get("data"))

    def _build_record_data(
            self, deployment_id: str, version: str, **kwargs: Any
    ) -> dict:
        create_model = DockerCreate(
            deployment_id=deployment_id,
            version=version,
            **kwargs
        )
        now = datetime.now()
        data = create_model.model_dump()
        data["created_at"] = now
        data["updated_at"] = now
        return data

    def _get_stop_kwargs(self, record: Any) -> dict:
        return {}

    def _get_status_kwargs(self, record: Any) -> dict:
        return {}
