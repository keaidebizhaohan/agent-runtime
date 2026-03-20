import os
from .sqlalchemy_handler import SQLAlchemyHandler


class MySQLHandler(SQLAlchemyHandler):
    """MySQL数据库句柄"""

    def __init__(
        self
    ):
        self.host = os.getenv("DB_HOST")
        self.port = int(os.getenv("DB_PORT"))
        self.database = os.getenv("DB_NAME")
        self.user = os.getenv("DB_USER")
        self.password = os.getenv("DB_PASSWORD")

        database_url = f"mysql+aiomysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        super().__init__(database_url)
