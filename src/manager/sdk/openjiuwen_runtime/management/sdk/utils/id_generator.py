"""ID 生成器"""

import time
import uuid


def generate_deployment_id(prefix: str = "dep") -> str:
    """生成部署 ID"""
    # 使用时间戳 + UUID 生成唯一 ID
    timestamp = int(time.time() * 1000)
    unique_id = uuid.uuid4().hex[:8]
    return f"{prefix}_{timestamp}_{unique_id}"
