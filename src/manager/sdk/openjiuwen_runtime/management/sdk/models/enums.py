"""枚举定义"""

from enum import Enum


class DeploymentType(str, Enum):
    """部署类型"""
    AGENT = "agent"
    PLUGIN = "plugin"


class DeploymentStatus(str, Enum):
    """部署状态"""
    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
