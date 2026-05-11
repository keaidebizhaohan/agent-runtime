# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

from typing import Optional
from urllib.parse import quote_plus

from .sqlalchemy_handler import SQLAlchemyHandler
from ..config import settings


class MySQLHandler(SQLAlchemyHandler):
    """MySQL数据库句柄

    连接参数可在构造函数中显式传入；未传入的字段使用 ``settings``（环境变量）中的值。
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.host = host if host is not None else settings.DB_HOST
        self.port = port if port is not None else settings.DB_PORT
        self.database = database if database is not None else settings.DB_NAME
        self.user = user if user is not None else settings.DB_USER
        self.password = password if password is not None else settings.DB_PASSWORD

        database_url = (
            f"mysql+aiomysql://{quote_plus(self.user or '')}:{quote_plus(self.password or '')}"
            f"@{self.host}:{self.port}/{self.database}"
        )
        super().__init__(database_url)
