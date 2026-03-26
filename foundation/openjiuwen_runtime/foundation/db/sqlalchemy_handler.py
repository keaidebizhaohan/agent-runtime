from datetime import datetime
import logging
from typing import Optional, Any

from sqlalchemy import Column, Integer, String, DateTime, JSON, Boolean, create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select, update, delete

from .handler import DBHandler
from .table_def import TableDefinition, ColumnDefinition

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class GenericRecord:
    """通用记录类，用于动态表操作"""
    pass


class SQLAlchemyHandler(DBHandler):
    """SQLAlchemy基类实现"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = None
        self.session_factory = None
        self._table_models: dict[str, Any] = {}
        logger.debug("SQLAlchemyHandler created")

    async def connect(self) -> None:
        logger.info("Connecting to database")
        # 关闭 aiosqlite 的 DEBUG 日志
        logging.getLogger("aiosqlite").setLevel(logging.WARNING)
        self.engine = create_async_engine(self.database_url, echo=False)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        logger.info("Database connected")

    async def disconnect(self) -> None:
        logger.info("Disconnecting from database")
        if self.engine:
            await self.engine.dispose()
        logger.info("Database disconnected")

    def _get_sqlalchemy_type(self, data_type: str, length: Optional[int] = None):
        """将数据类型字符串转换为 SQLAlchemy 类型"""
        type_map = {
            "integer": Integer,
            "int": Integer,
            "string": String,
            "str": String,
            "text": String,
            "datetime": DateTime,
            "json": JSON,
            "boolean": Boolean,
            "bool": Boolean,
        }
        sa_type = type_map.get(data_type.lower(), String)
        if sa_type == String and length:
            return String(length)
        return sa_type

    async def init_table(self, table_def: TableDefinition) -> None:
        """初始化表（存在则跳过，不存在则创建）"""
        logger.debug(f"Initializing table: table_name={table_def.table_name}")
        columns = []
        for col_def in table_def.columns:
            sa_type = self._get_sqlalchemy_type(col_def.data_type, col_def.length)
            col_kwargs = {
                "primary_key": col_def.primary_key,
                "nullable": col_def.nullable,
                "unique": col_def.unique,
                "autoincrement": col_def.autoincrement,
            }
            if col_def.default is not None:
                col_kwargs["default"] = col_def.default
            if sa_type == String and col_def.length:
                col = Column(sa_type(col_def.length), **col_kwargs)
            else:
                col = Column(sa_type, **col_kwargs)
            columns.append(col)

        table = type(
            table_def.table_name.capitalize() + "Record",
            (Base,),
            {
                "__tablename__": table_def.table_name,
                "__table_args__": {"extend_existing": True},
                **{col_def.name: col for col_def, col in zip(table_def.columns, columns)},
                "to_dict": lambda self: {
                    col.name: getattr(self, col.name) for col in table_def.columns
                },
            },
        )

        self._table_models[table_def.table_name] = table

        async with self.engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(
                    sync_conn, tables=[table.__table__]
                )
            )
        logger.debug(f"Table initialized: table_name={table_def.table_name}")

    async def _get_session(self) -> AsyncSession:
        return self.session_factory()

    async def create(self, table_name: str, data: dict) -> Any:
        logger.debug(f"Creating record: table={table_name}")
        model = self._table_models.get(table_name)
        if not model:
            logger.error(f"Table not initialized: table={table_name}")
            raise ValueError(f"Table {table_name} not initialized")

        async with await self._get_session() as session:
            record = model(**data)
            session.add(record)
            await session.commit()
            await session.refresh(record)
            logger.debug(f"Record created: table={table_name}")
            return record

    async def get(self, table_name: str, filters: dict) -> Optional[Any]:
        logger.debug(f"Getting record: table={table_name}, filters={filters}")
        model = self._table_models.get(table_name)
        if not model:
            logger.error(f"Table not initialized: table={table_name}")
            raise ValueError(f"Table {table_name} not initialized")

        async with await self._get_session() as session:
            query = select(model)
            for key, value in filters.items():
                query = query.where(getattr(model, key) == value)
            result = await session.execute(query)
            record = result.scalar_one_or_none()
            logger.debug(f"Record found: table={table_name}, found={record is not None}")
            return record

    async def update(self, table_name: str, filters: dict, data: dict) -> Optional[Any]:
        logger.debug(f"Updating record: table={table_name}, filters={filters}")
        model = self._table_models.get(table_name)
        if not model:
            logger.error(f"Table not initialized: table={table_name}")
            raise ValueError(f"Table {table_name} not initialized")

        async with await self._get_session() as session:
            query = update(model)
            for key, value in filters.items():
                query = query.where(getattr(model, key) == value)
            query = query.values(**data)
            await session.execute(query)
            await session.commit()
            logger.debug(f"Record updated: table={table_name}")
            return await self.get(table_name, filters)

    async def delete(self, table_name: str, filters: dict) -> bool:
        logger.debug(f"Deleting record: table={table_name}, filters={filters}")
        model = self._table_models.get(table_name)
        if not model:
            logger.error(f"Table not initialized: table={table_name}")
            raise ValueError(f"Table {table_name} not initialized")

        async with await self._get_session() as session:
            query = delete(model)
            for key, value in filters.items():
                query = query.where(getattr(model, key) == value)
            result = await session.execute(query)
            await session.commit()
            deleted = result.rowcount > 0
            logger.debug(f"Record deleted: table={table_name}, deleted={deleted}")
            return deleted

    async def list_records(
        self,
        table_name: str,
        filters: Optional[dict] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Any]:
        logger.debug(f"Listing records: table={table_name}, filters={filters}, limit={limit}, offset={offset}")
        model = self._table_models.get(table_name)
        if not model:
            logger.error(f"Table not initialized: table={table_name}")
            raise ValueError(f"Table {table_name} not initialized")

        async with await self._get_session() as session:
            query = select(model)
            if filters:
                for key, value in filters.items():
                    query = query.where(getattr(model, key) == value)
            query = query.offset(offset).limit(limit)
            result = await session.execute(query)
            records = list(result.scalars().all())
            logger.debug(f"Records listed: table={table_name}, count={len(records)}")
            return records
