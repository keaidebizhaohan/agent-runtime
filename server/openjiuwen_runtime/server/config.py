"""Server Configuration"""

import os
from dotenv import load_dotenv

# 加载 .env 配置
load_dotenv()


class Settings:
    """服务器配置"""

    # MySQL
    MYSQL_HOST: str = os.getenv("DB_HOST", "localhost")
    MYSQL_PORT: int = int(os.getenv("DB_PORT", "3306"))
    MYSQL_DATABASE: str = os.getenv("DB_NAME", "agent_runtime")
    MYSQL_USER: str = os.getenv("DB_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("DB_PASSWORD", "")

    # OSS
    OSS_ENDPOINT: str = os.getenv("OSS_ENDPOINT", "")
    OSS_BUCKET: str = os.getenv("OSS_BUCKET", "")
    OSS_ACCESS_KEY: str = os.getenv("OSS_ACCESS_KEY", "")
    OSS_SECRET_KEY: str = os.getenv("OSS_SECRET_KEY", "")


settings = Settings()
