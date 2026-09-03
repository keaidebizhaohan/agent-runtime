# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from openjiuwen_runtime.management import DeploymentManager, DeployMode
from openjiuwen_runtime.management.models.enums import DeploymentStatus, DeploymentType
from openjiuwen_runtime.management.models.schemas import DeploymentInfo


def _running_deployment() -> DeploymentInfo:
    now = datetime.utcnow()
    return DeploymentInfo(
        id=1,
        deployment_id="test-deployment",
        version="1.0.0",
        deployment_type=DeploymentType.AGENT,
        deployment_status=DeploymentStatus.RUNNING,
        name="test-agent",
        url="http://127.0.0.1:8090",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_k8s_readiness_does_not_require_host_http_health() -> None:
    manager = DeploymentManager(
        db_handler=AsyncMock(),
        strategies={DeployMode.K8S: AsyncMock()},
    )
    manager.get_deployment = AsyncMock(return_value=_running_deployment())
    manager._check_health_endpoint = AsyncMock(
        side_effect=AssertionError("K8s readiness must not probe a host URL")
    )

    await manager._wait_until_deployment_ready(
        "test-deployment",
        timeout_seconds=1,
        interval_seconds=0,
        require_http_health=False,
    )

    manager._check_health_endpoint.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_k8s_readiness_still_requires_http_health() -> None:
    manager = DeploymentManager(
        db_handler=AsyncMock(),
        strategies={DeployMode.SUBPROCESS: AsyncMock()},
    )
    manager.get_deployment = AsyncMock(return_value=_running_deployment())
    manager._check_health_endpoint = AsyncMock(return_value=True)

    await manager._wait_until_deployment_ready(
        "test-deployment",
        timeout_seconds=1,
        interval_seconds=0,
    )

    manager._check_health_endpoint.assert_awaited_once_with("http://127.0.0.1:8090")
