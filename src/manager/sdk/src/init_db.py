"""数据库初始化"""

from .database.mysql import MySQLDatabase


def init_database():
    """初始化数据库表"""
    db = MySQLDatabase()
    db.create_tables()