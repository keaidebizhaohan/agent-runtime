"""部署记录模型 (v2.1)

v2.0 新增字段:
- venv_path: 虚拟环境路径
- package_name: Python包名
- whl_path: WHL包路径

v2.1 新增字段:
- user_id: 用户ID（租户隔离）
- space_id: 空间ID（租户隔离）
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy.ext.declarative import declarative_base

from .enums import DeploymentType, DeploymentStatus

Base = declarative_base()


class Deployment(BaseModel):
    """部署记录模型 (Pydantic) v2.1"""

    deployment_id: str
    type: DeploymentType
    name: str  # 部署名称=包名（必填）
    status: DeploymentStatus

    # 租户字段 (v2.1 新增)
    user_id: str
    space_id: str

    # 部署信息
    url: Optional[str] = None
    deployer_type: str
    port: int
    pid: Optional[int] = None

    # v2.0 新增字段
    venv_path: Optional[str] = None
    package_name: Optional[str] = None
    whl_path: Optional[str] = None

    # 时间戳
    created_at: str
    updated_at: str

    # 可选的额外信息
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DeploymentDB(Base):
    """部署记录表 (SQLAlchemy ORM) v2.1"""

    __tablename__ = "deployments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    deployment_id = Column(String(64), unique=True, nullable=False, index=True)
    type = Column(String(20), nullable=False)
    name = Column(String(255), nullable=False)  # 部署名称=包名（必填）
    status = Column(String(20), nullable=False, index=True)

    # 租户字段 (v2.1 新增)
    user_id = Column(String(64), nullable=False, index=True)
    space_id = Column(String(64), nullable=False, index=True)

    # 部署信息
    url = Column(String(512), nullable=True)
    deployer_type = Column(String(50), nullable=False)
    port = Column(Integer, nullable=False)
    pid = Column(Integer, nullable=True)

    # v2.0 新增字段
    venv_path = Column(String(512), nullable=True)
    package_name = Column(String(255), nullable=True)
    whl_path = Column(String(512), nullable=True)

    # 时间戳
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # 错误信息
    error_message = Column(Text, nullable=True)

    # 复合索引：支持按用户+空间快速查询
    __table_args__ = (
        Index('idx_user_space', 'user_id', 'space_id'),
    )

    def to_pydantic(self) -> Deployment:
        """转换为 Pydantic 模型"""
        return Deployment(
            deployment_id=self.deployment_id,
            type=self.type,
            name=self.name,
            status=self.status,
            user_id=self.user_id,
            space_id=self.space_id,
            url=self.url,
            deployer_type=self.deployer_type,
            port=self.port,
            pid=self.pid,
            venv_path=self.venv_path,
            package_name=self.package_name,
            whl_path=self.whl_path,
            created_at=self.created_at.isoformat(),
            updated_at=self.updated_at.isoformat(),
            error_message=self.error_message,
        )
