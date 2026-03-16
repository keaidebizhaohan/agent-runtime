"""Deployer 抽象基类"""

from abc import ABC, abstractmethod
from typing import Dict, Any

from ..models.enums import DeploymentStatus


class Deployer(ABC):
    """Deployer 抽象基类"""

    @abstractmethod
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
        部署应用 - 启动 Python 子进程

        Args:
            whl_path: WHL 包路径（由 Manager SDK 内部打包生成）
            name: 部署名称=包名（用于 python -m 运行）
            deployment_id: 部署唯一标识
            port: 服务端口
            host: 服务主机
            **kwargs: 其他部署参数

        Returns:
            部署信息字典
        """
        pass

    @abstractmethod
    async def stop(self, deployment: dict) -> bool:
        """停止部署

        Args:
            deployment: 部署信息字典，包含 deployment_id 和 pid
        """
        pass

    @abstractmethod
    async def get_status(self, deployment: dict) -> DeploymentStatus:
        """获取部署状态

        Args:
            deployment: 部署信息字典，包含 deployment_id 和 pid
        """
        pass
