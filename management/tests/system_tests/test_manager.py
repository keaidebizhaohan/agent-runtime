# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

"""部署管理器测试"""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from openjiuwen_runtime.foundation.log import get_logger
from openjiuwen_runtime.management import (
    DeployAgentParams,
    DeploymentManager,
    DeployMode,
)
from openjiuwen_runtime.foundation.db.sqlite_handler import SQLiteHandler
from openjiuwen_runtime.foundation.packaging import package_python_to_whl

logger = get_logger(__name__)


class ManagerTest(unittest.IsolatedAsyncioTestCase):
    """部署管理器测试"""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="deployment_test_")
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.venv_base_path = os.path.join(self.temp_dir, "venvs")

        self.db_handler = SQLiteHandler(self.db_path)
        self.manager = DeploymentManager(
            db_handler=self.db_handler,
        )
        await self.manager.initialize()

    async def asyncTearDown(self):
        await self.manager.shutdown()

        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    @unittest.skip("skip")
    async def test_deploy_simple_agent(self):
        """测试部署 simple_agent"""
        project_root = Path(__file__).parent.parent
        simple_agent_dir = project_root / "resources" / "examples" / "simple_agent"

        self.assertTrue(simple_agent_dir.exists(), f"simple_agent directory not found: {simple_agent_dir}")

        with tempfile.TemporaryDirectory(prefix="whl_build_") as build_dir:
            whl_path = await package_python_to_whl(
                source_dir=str(simple_agent_dir),
                output_dir=build_dir,
                package_name="simple_agent",
            )

            self.assertTrue(os.path.exists(whl_path), f"WHL file not found: {whl_path}")

            deployment_info = await self.manager.deploy_agent(
                DeployAgentParams(
                    name="test_simple_agent",
                    version="1.0.0",
                    mode=DeployMode.SUBPROCESS,
                    extras={"package_name": "simple_agent", "whl_path": whl_path},
                )
            )

            self.assertIsNotNone(deployment_info)
            self.assertEqual(deployment_info.name, "test_simple_agent")
            self.assertIsNotNone(deployment_info.url)

            import aiohttp
            await asyncio.sleep(3)

            async with aiohttp.ClientSession() as session:
                async with session.get(f"{deployment_info.url}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    self.assertEqual(resp.status, 200)
                    data = await resp.json()
                    self.assertEqual(data.get("status"), "healthy")

            process_info = await self.manager.get_process_info(deployment_info.deployment_id)
            self.assertIsNotNone(process_info)
            self.assertIsNotNone(process_info.pid)

            success = await self.manager.stop_deployment(deployment_info.deployment_id)
            self.assertTrue(success)

            status = await self.manager.get_deployment_status(deployment_info.deployment_id)
            from openjiuwen_runtime.management.models.enums import DeploymentStatus
            self.assertEqual(status, DeploymentStatus.STOPPED)

    # @unittest.skip("skip")
    async def test_deploy_simple_agent_whl(self):
        """测试部署 simple_agent"""
        with tempfile.TemporaryDirectory(prefix="whl_build_") as build_dir:
            project_root = Path(__file__).parent.parent
            whl_path = str(
                project_root / "resources" / "examples" / "simple_agent" / "openjiuwen_agent-1.0.0-py3-none-any.whl")

            deployment_info = await self.manager.deploy_agent(
                DeployAgentParams(
                    name="test_simple_agent",
                    version="1.0.0",
                    mode=DeployMode.SUBPROCESS,
                    extras={"package_name": "simple_agent", "whl_path": whl_path},
                )
            )

            self.assertIsNotNone(deployment_info)
            self.assertEqual(deployment_info.name, "test_simple_agent")
            self.assertIsNotNone(deployment_info.url)

            import aiohttp
            await asyncio.sleep(3)

            async with aiohttp.ClientSession() as session:
                async with session.get(f"{deployment_info.url}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    self.assertEqual(resp.status, 200)
                    data = await resp.json()
                    self.assertEqual(data.get("status"), "healthy")

            process_info = await self.manager.get_process_info(deployment_info.deployment_id)
            self.assertIsNotNone(process_info)
            self.assertIsNotNone(process_info.pid)

            success = await self.manager.stop_deployment(deployment_info.deployment_id)
            self.assertTrue(success)

            status = await self.manager.get_deployment_status(deployment_info.deployment_id)
            from openjiuwen_runtime.management.models.enums import DeploymentStatus
            self.assertEqual(status, DeploymentStatus.STOPPED)


if __name__ == '__main__':
    a = ManagerTest()
    asyncio.run(a.asyncSetUp())
    result = asyncio.run(a.test_deploy_simple_agent_whl())
    asyncio.run(a.asyncTearDown())
    logger.info("%s", result)
