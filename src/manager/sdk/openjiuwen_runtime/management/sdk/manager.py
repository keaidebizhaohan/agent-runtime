"""部署管理器 (v2.0)

v2.0 特性:
- 支持Python文件自动打包为WHL包
- 虚拟环境隔离
- 统一使用name参数作为部署名称和包名
"""

import logging
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from .foundation.log import get_logger
from .models.enums import DeploymentType, DeploymentStatus
from .database.mysql import MySQLDatabase
from .deployer.local_subprocess import LocalSubprocessDeployer
from .utils.id_generator import generate_deployment_id
from .utils.port_manager import allocate_port

logger = get_logger(__name__)


class DeploymentManager:
    """部署管理器 (v2.0)"""

    def __init__(
            self,
            default_deployer_type: str = "local_subprocess",
            venvs_root: str = "./venvs",
    ):
        """初始化部署管理器

        Args:
            default_deployer_type: 默认部署器类型
            venvs_root: 虚拟环境根目录
        """
        self.db = MySQLDatabase()
        self.default_deployer_type = default_deployer_type
        self.venvs_root = venvs_root
        self.deployers: Dict[str, LocalSubprocessDeployer] = {}
        self._init_deployers()

    def _init_deployers(self):
        """初始化部署器"""
        self.deployers["local_subprocess"] = LocalSubprocessDeployer(
            venvs_root=self.venvs_root
        )

    def package_python_to_whl(
            self,
            python_file_path: str,
            name: str,
            temp_dir: Optional[str] = None,
    ) -> str:
        """
        将 Python 文件打包为 WHL 包

        Args:
            python_file_path: Python 文件路径
            name: 部署名称（仅用于显示，不用于包名）
            temp_dir: 临时目录（可选，默认使用系统临时目录）

        Returns:
            WHL 包文件路径
        """
        # 统一使用固定包名，避免中文名问题
        package_name = "openjiuwen_agent"

        # 读取 Python 文件内容
        python_file = Path(python_file_path)
        if not python_file.exists():
            raise FileNotFoundError(f"Python file not found: {python_file_path}")

        code_content = python_file.read_text(encoding='utf-8')

        # 读取依赖文件（如果有）
        install_requires = []
        requirements_file = python_file.parent / "requirements.txt"
        if requirements_file.exists():
            requirements_content = requirements_file.read_text(encoding='utf-8')
            for line in requirements_content.strip().split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    install_requires.append(line)
            logger.info(f"Found {len(install_requires)} dependencies in requirements.txt")

        # 创建临时打包目录
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp(prefix="whl_build_")
        else:
            Path(temp_dir).mkdir(parents=True, exist_ok=True)

        try:
            # 创建包目录结构（使用固定包名）
            package_dir = Path(temp_dir) / package_name
            package_dir.mkdir(exist_ok=True)

            # 创建 __main__.py
            main_py = package_dir / "__main__.py"
            main_py.write_text(code_content, encoding='utf-8')

            # 创建 setup.py（使用固定包名）
            setup_py = Path(temp_dir) / "setup.py"
            # 显式处理 install_requires，确保格式正确
            if install_requires:
                install_requires_str = str(install_requires).replace("'", '"')
            else:
                install_requires_str = "[]"

            setup_content = f'''from setuptools import setup, find_packages

setup(
    name="{package_name}",
    version="1.0.0",
    packages=find_packages(),
    py_modules=["{package_name}.__main__"],
    install_requires={install_requires_str},
)
'''
            setup_py.write_text(setup_content, encoding='utf-8')
            logger.info(f"Generated setup.py:\n{setup_content}")

            # 使用 subprocess 调用 build 命令打包
            import subprocess
            result = subprocess.run(
                [sys.executable, "-m", "build", "--wheel", str(temp_dir)],
                capture_output=True,
                text=True,
                cwd=temp_dir
            )

            if result.returncode != 0:
                raise RuntimeError(f"Failed to build WHL: {result.stderr}")

            # 查找生成的 WHL 文件
            dist_dir = Path(temp_dir) / "dist"
            whl_files = list(dist_dir.glob("*.whl"))
            if not whl_files:
                raise RuntimeError(f"No WHL file generated in {dist_dir}")

            whl_path = str(whl_files[0])
            logger.info(f"Built WHL package: {whl_path}")

            return whl_path
        except Exception as e:
            # 清理临时目录
            if Path(temp_dir).exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(f"Failed to package Python file: {e}")

    def _get_deployer(self, deployer_type: str) -> LocalSubprocessDeployer:
        """获取部署器"""
        deployer = self.deployers.get(deployer_type)
        if not deployer:
            raise ValueError(f"Unknown deployer type: {deployer_type}")
        return deployer

    async def deploy_agent(
            self,
            python_file_path: str,
            name: str,
            deployer_type: str = None,
            port: Optional[int] = None,
            user_id: Optional[str] = None,
            space_id: Optional[str] = None,
            **deployer_kwargs
    ) -> Dict[str, Any]:
        """
        部署 Agent (v2.1 - 支持租户隔离)

        使用Python文件部署Agent，内部自动打包为WHL包，支持虚拟环境隔离。
        name 参数既是部署名称，也是打包的包名。

        Args:
            python_file_path: Python 文件路径
            name: 部署名称=包名（用于打包和 python -m 运行）
            deployer_type: 部署器类型
            port: 服务端口
            user_id: 用户ID（租户隔离，CLI可选）
            space_id: 空间ID（租户隔离，CLI可选）
            **deployer_kwargs: 其他部署参数

        Returns:
            部署信息
        """
        # 内部将 Python 文件打包为 WHL
        whl_path = self.package_python_to_whl(python_file_path, name)

        deployer_type = deployer_type or self.default_deployer_type
        deployer = self._get_deployer(deployer_type)

        # 分配端口
        if port is None:
            port = allocate_port(start_port=8090, max_port=9090)

        # 生成部署 ID
        deployment_id = generate_deployment_id("agent")

        logger.info(f"Deploying agent: {deployment_id} from {python_file_path} on port {port}")

        # 创建部署记录
        now = datetime.now().isoformat()
        deployment_record = {
            "deployment_id": deployment_id,
            "type": DeploymentType.AGENT,
            "name": name,  # 部署名称（用户输入，可以是中文）
            "status": DeploymentStatus.PENDING,
            # v2.1 新增：租户字段
            "user_id": user_id or "admin",  # CLI 默认使用 admin
            "space_id": space_id or "default",  # CLI 默认使用 default
            "url": None,
            "deployer_type": deployer_type,
            "port": port,
            "pid": None,
            # v2.0 新增字段
            "venv_path": f"{self.venvs_root}/{deployment_id}",
            "package_name": "openjiuwen_agent",  # 固定包名
            "whl_path": whl_path,
            # 时间戳
            "created_at": now,
            "updated_at": now,
            "error_message": None,
        }

        await self.db.create_deployment(deployment_record)

        try:
            # 使用部署器部署（使用固定包名运行）
            result = await deployer.deploy(
                whl_path=whl_path,
                name="openjiuwen_agent",  # 固定包名，用于 python -m
                deployment_id=deployment_id,
                port=port,
                **deployer_kwargs
            )

            # 更新部署状态
            await self.db.update_deployment_status(
                deployment_id,
                DeploymentStatus.RUNNING,
                url=result["url"],
                pid=result["pid"],
                venv_path=result["venv_path"],
            )

            logger.info(f"Agent deployed: {deployment_id} on port {port}")
            return {
                "deployment_id": deployment_id,
                "type": DeploymentType.AGENT,
                "name": name,
                "url": result["url"],
                "status": DeploymentStatus.RUNNING,
                "port": port,
            }
        except Exception as e:
            # 部署失败
            await self.db.update_deployment_status(
                deployment_id,
                DeploymentStatus.FAILED,
                error_message=str(e),
            )
            logger.error(f"Agent deployment failed: {deployment_id} - {e}")
            raise

    async def deploy_plugin(
            self,
            python_file_path: str,
            name: str,
            deployer_type: str = None,
            port: Optional[int] = None,
            user_id: Optional[str] = None,
            space_id: Optional[str] = None,
            **deployer_kwargs
    ) -> Dict[str, Any]:
        """
        部署 Plugin (v2.1 - 支持租户隔离)

        使用Python文件部署Plugin，内部自动打包为WHL包，支持虚拟环境隔离。
        name 参数既是部署名称，也是打包的包名。

        Args:
            python_file_path: Python 文件路径
            name: 部署名称=包名（用于打包和 python -m 运行）
            deployer_type: 部署器类型
            port: 服务端口
            user_id: 用户ID（租户隔离，CLI可选）
            space_id: 空间ID（租户隔离，CLI可选）
            **deployer_kwargs: 其他部署参数

        Returns:
            部署信息
        """
        # 内部将 Python 文件打包为 WHL
        whl_path = self.package_python_to_whl(python_file_path, name)

        deployer_type = deployer_type or self.default_deployer_type
        deployer = self._get_deployer(deployer_type)

        # 分配端口
        if port is None:
            port = allocate_port(start_port=8091, max_port=9091)

        # 生成部署 ID
        deployment_id = generate_deployment_id("plugin")

        logger.info(f"Deploying plugin: {deployment_id} from {python_file_path} on port {port}")

        # 创建部署记录
        now = datetime.now().isoformat()
        deployment_record = {
            "deployment_id": deployment_id,
            "type": DeploymentType.PLUGIN,
            "name": name,  # 部署名称（用户输入，可以是中文）
            "status": DeploymentStatus.PENDING,
            # v2.1 新增：租户字段
            "user_id": user_id or "admin",
            "space_id": space_id or "default",
            "url": None,
            "deployer_type": deployer_type,
            "port": port,
            "pid": None,
            # v2.0 新增字段
            "venv_path": f"{self.venvs_root}/{deployment_id}",
            "package_name": "openjiuwen_agent",  # 固定包名
            "whl_path": whl_path,
            # 时间戳
            "created_at": now,
            "updated_at": now,
            "error_message": None,
        }

        await self.db.create_deployment(deployment_record)

        try:
            # 使用部署器部署（使用固定包名运行）
            result = await deployer.deploy(
                whl_path=whl_path,
                name="openjiuwen_agent",  # 固定包名，用于 python -m
                deployment_id=deployment_id,
                port=port,
                **deployer_kwargs
            )

            # 更新部署状态
            await self.db.update_deployment_status(
                deployment_id,
                DeploymentStatus.RUNNING,
                url=result["url"],
                pid=result["pid"],
                venv_path=result["venv_path"],
            )

            logger.info(f"Plugin deployed: {deployment_id} on port {port}")
            return {
                "deployment_id": deployment_id,
                "type": DeploymentType.PLUGIN,
                "name": name,
                "url": result["url"],
                "status": DeploymentStatus.RUNNING,
                "port": port,
            }
        except Exception as e:
            # 部署失败
            await self.db.update_deployment_status(
                deployment_id,
                DeploymentStatus.FAILED,
                error_message=str(e),
            )
            logger.error(f"Plugin deployment failed: {deployment_id} - {e}")
            raise

    async def list_deployments(
            self,
            deployment_type: Optional[DeploymentType] = None,
            status: Optional[DeploymentStatus] = None,
            user_id: Optional[str] = None,
            space_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询部署列表（实时检查状态并更新数据库，支持租户过滤）

        Args:
            deployment_type: 部署类型过滤
            status: 状态过滤
            user_id: 用户ID（可选，用于租户隔离）
            space_id: 空间ID（可选，用于租户隔离）

        Returns:
            部署列表
        """
        logger.info(
            f"Listing deployments: type={deployment_type}, status={status}, user_id={user_id}, space_id={space_id}")
        type_str = deployment_type.value if deployment_type else None
        status_str = status.value if status else None
        deployments = await self.db.list_deployments(
            deployment_type=type_str,
            status=status_str,
            user_id=user_id,  # 租户过滤
            space_id=space_id,  # 租户过滤
        )

        # 实时检查每个部署的状态并更新数据库
        for deployment in deployments:
            deployer = self._get_deployer(deployment["deployer_type"])
            current_status = await deployer.get_status(deployment)
            if current_status.value != deployment["status"]:
                logger.info(
                    f"Deployment {deployment['deployment_id']} status changed: {deployment['status']} -> {current_status.value}")
                await self.db.update_deployment_status(
                    deployment["deployment_id"],
                    current_status.value,
                    user_id=user_id,  # 租户过滤
                    space_id=space_id,  # 租户过滤
                )

        # 重新查询返回最新状态
        return await self.db.list_deployments(
            deployment_type=type_str,
            status=status_str,
            user_id=user_id,  # 租户过滤
            space_id=space_id,  # 租户过滤
        )

    async def get_deployment(
            self,
            deployment_id: str,
            user_id: Optional[str] = None,
            space_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取部署详情（实时检查状态并更新数据库，支持租户过滤）

        Args:
            deployment_id: 部署ID
            user_id: 用户ID（可选，用于租户隔离）
            space_id: 空间ID（可选，用于租户隔离）

        Returns:
            部署详情，不存在则返回None
        """
        logger.debug(f"Getting deployment: {deployment_id}, user_id={user_id}, space_id={space_id}")
        deployment = await self.db.get_deployment(
            deployment_id,
            user_id=user_id,  # 租户过滤
            space_id=space_id,  # 租户过滤
        )
        if not deployment:
            logger.warning(f"Deployment not found: {deployment_id}")
            return None

        # 实时检查状态并更新数据库
        deployer = self._get_deployer(deployment["deployer_type"])
        current_status = await deployer.get_status(deployment)
        if current_status.value != deployment["status"]:
            logger.info(f"Deployment {deployment_id} status updated: {deployment['status']} -> {current_status.value}")
            await self.db.update_deployment_status(
                deployment_id,
                current_status.value,
                user_id=user_id,  # 租户过滤
                space_id=space_id,  # 租户过滤
            )
            deployment = await self.db.get_deployment(
                deployment_id,
                user_id=user_id,  # 租户过滤
                space_id=space_id,  # 租户过滤
            )

        return deployment

    async def delete_deployment(
            self,
            deployment_id: str,
            user_id: Optional[str] = None,
            space_id: Optional[str] = None,
    ) -> bool:
        """删除部署（包括虚拟环境清理，支持租户过滤）

        Args:
            deployment_id: 部署ID
            user_id: 用户ID（可选，用于租户隔离）
            space_id: 空间ID（可选，用于租户隔离）

        Returns:
            是否删除成功
        """
        logger.info(f"Deleting deployment: {deployment_id}, user_id={user_id}, space_id={space_id}")
        deployment = await self.get_deployment(
            deployment_id,
            user_id=user_id,  # 租户过滤
            space_id=space_id,  # 租户过滤
        )
        if not deployment:
            logger.warning(f"Deployment not found for deletion: {deployment_id}")
            return False

        # 根据状态决定是否需要停止
        status = deployment["status"]
        if status in (DeploymentStatus.RUNNING, DeploymentStatus.PENDING):
            # 需要先停止
            deployer_type = deployment["deployer_type"]
            deployer = self._get_deployer(deployer_type)
            success = await deployer.stop(deployment)
            if not success:
                logger.warning(f"Failed to stop deployment {deployment_id}, deleting anyway")
        else:
            # 已停止或失败，直接删除
            logger.info(f"Deployment {deployment_id} is {status}, skipping stop")

        # 删除记录
        db_success = await self.db.delete_deployment(
            deployment_id,
            user_id=user_id,  # 租户过滤
            space_id=space_id,  # 租户过滤
        )
        logger.info(f"Deployment {deployment_id} deleted")
        return db_success
