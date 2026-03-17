from .sqlalchemy_handler import SQLAlchemyHandler


class SQLiteHandler(SQLAlchemyHandler):
    """SQLite数据库句柄"""

    def __init__(self, db_path: str = "deployment_service.db"):
        database_url = f"sqlite+aiosqlite:///{db_path}"
        super().__init__(database_url)
