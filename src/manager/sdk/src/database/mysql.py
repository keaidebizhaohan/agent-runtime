"""MySQL 数据库实现"""

import os
from typing import List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from ..models.deployment import DeploymentDB, Base, Deployment


class MySQLDatabase:
    """MySQL 数据库"""

    def __init__(self):
        """初始化 MySQL 数据库连接"""
        self.host = os.getenv("DB_HOST")
        self.port = int(os.getenv("DB_PORT"))
        self.database = os.getenv("DB_NAME")
        self.user = os.getenv("DB_USER")
        self.password = os.getenv("DB_PASSWORD")

        # 构建 URL
        self.url = f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

        # 创建引擎
        self.engine = create_engine(
            self.url,
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False,
        )

        # 创建 Session 工厂
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def create_tables(self):
        """创建数据库表"""
        Base.metadata.create_all(bind=self.engine)

    def get_session(self) -> Session:
        """获取数据库会话"""
        return self.SessionLocal()

    async def create_deployment(self, deployment: dict) -> str:
        """创建部署记录"""
        with self.get_session() as session:
            db_deployment = DeploymentDB(**deployment)
            session.add(db_deployment)
            session.commit()
            session.refresh(db_deployment)
            return db_deployment.deployment_id

    async def get_deployment(
        self,
        deployment_id: str,
        user_id: Optional[str] = None,
        space_id: Optional[str] = None,
    ) -> Optional[dict]:
        """获取单个部署记录

        Args:
            deployment_id: 部署ID
            user_id: 用户ID（可选，用于租户隔离）
            space_id: 空间ID（可选，用于租户隔离）

        Returns:
            部署记录字典，不存在则返回None
        """
        with self.get_session() as session:
            query = session.query(DeploymentDB).filter(
                DeploymentDB.deployment_id == deployment_id
            )

            # 租户隔离过滤（仅当提供了 user_id 和 space_id 时）
            if user_id is not None and space_id is not None:
                query = query.filter(
                    DeploymentDB.user_id == user_id,
                    DeploymentDB.space_id == space_id,
                )

            db_deployment = query.first()
            if db_deployment:
                return db_deployment.to_pydantic().model_dump()
            return None

    async def list_deployments(
        self,
        deployment_type: Optional[str] = None,
        status: Optional[str] = None,
        user_id: Optional[str] = None,
        space_id: Optional[str] = None,
    ) -> List[dict]:
        """查询部署列表

        Args:
            deployment_type: 部署类型过滤
            status: 状态过滤
            user_id: 用户ID（可选，用于租户隔离）
            space_id: 空间ID（可选，用于租户隔离）

        Returns:
            部署记录列表
        """
        with self.get_session() as session:
            query = session.query(DeploymentDB)

            # 类型过滤
            if deployment_type:
                query = query.filter(DeploymentDB.type == deployment_type)

            # 状态过滤
            if status:
                query = query.filter(DeploymentDB.status == status)

            # 租户隔离过滤（仅当提供了 user_id 和 space_id 时）
            if user_id is not None and space_id is not None:
                query = query.filter(
                    DeploymentDB.user_id == user_id,
                    DeploymentDB.space_id == space_id,
                )

            deployments = query.order_by(DeploymentDB.created_at.desc()).all()
            return [d.to_pydantic().model_dump() for d in deployments]

    async def update_deployment_status(
        self,
        deployment_id: str,
        status: str,
        user_id: Optional[str] = None,
        space_id: Optional[str] = None,
        **kwargs
    ) -> bool:
        """更新部署状态

        Args:
            deployment_id: 部署ID
            status: 新状态
            user_id: 用户ID（可选，用于租户隔离）
            space_id: 空间ID（可选，用于租户隔离）
            **kwargs: 其他要更新的字段

        Returns:
            是否更新成功
        """
        with self.get_session() as session:
            query = session.query(DeploymentDB).filter(
                DeploymentDB.deployment_id == deployment_id
            )

            # 租户隔离过滤（仅当提供了 user_id 和 space_id 时）
            if user_id is not None and space_id is not None:
                query = query.filter(
                    DeploymentDB.user_id == user_id,
                    DeploymentDB.space_id == space_id,
                )

            db_deployment = query.first()
            if db_deployment:
                db_deployment.status = status
                for key, value in kwargs.items():
                    if hasattr(db_deployment, key):
                        setattr(db_deployment, key, value)
                session.commit()
                return True
            return False

    async def delete_deployment(
        self,
        deployment_id: str,
        user_id: Optional[str] = None,
        space_id: Optional[str] = None,
    ) -> bool:
        """删除部署记录

        Args:
            deployment_id: 部署ID
            user_id: 用户ID（可选，用于租户隔离）
            space_id: 空间ID（可选，用于租户隔离）

        Returns:
            是否删除成功
        """
        with self.get_session() as session:
            query = session.query(DeploymentDB).filter(
                DeploymentDB.deployment_id == deployment_id
            )

            # 租户隔离过滤（仅当提供了 user_id 和 space_id 时）
            if user_id is not None and space_id is not None:
                query = query.filter(
                    DeploymentDB.user_id == user_id,
                    DeploymentDB.space_id == space_id,
                )

            db_deployment = query.first()
            if db_deployment:
                session.delete(db_deployment)
                session.commit()
                return True
            return False
