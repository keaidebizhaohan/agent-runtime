from .sqlalchemy_handler import SQLAlchemyHandler


class MySQLHandler(SQLAlchemyHandler):
    """MySQL数据库句柄"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        database: str = "deployment_service",
    ):
        database_url = f"mysql+aiomysql://{user}:{password}@{host}:{port}/{database}"
        super().__init__(database_url)
