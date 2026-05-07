# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

import os
from .sqlalchemy_handler import SQLAlchemyHandler
from ..config import settings


class MySQLHandler(SQLAlchemyHandler):
    """MySQL数据库句柄"""

    def __init__(
        self
    ):
        self.host = settings.RUNTIME_DB_HOST
        self.port = settings.RUNTIME_DB_PORT
        self.database = settings.RUNTIME_DB_NAME
        self.user = settings.RUNTIME_DB_USER
        self.password = settings.RUNTIME_DB_PASSWORD

        database_url = f"mysql+aiomysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        super().__init__(database_url)
