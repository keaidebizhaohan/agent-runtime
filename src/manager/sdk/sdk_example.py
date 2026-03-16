"""SDK使用示例

使用前请先初始化数据库：
    from openjiuwen_runtime.management.sdk import init_database
    init_database()
"""

import asyncio
from pathlib import Path
from dotenv import load_dotenv

from openjiuwen_runtime.management.sdk import DeploymentManager

# 加载.env配置文件（manager根目录）
_manager_root = Path(__file__).parent.parent
_env_file = _manager_root / ".env"
load_dotenv(_env_file)


async def main():
    """SDK使用示例"""

    # 创建部署管理器
    manager = DeploymentManager()

    # 部署Agent
    print("Deploying agent...")
    result = await manager.deploy_agent(
        local_file_path=str(Path(__file__).parent / "mock_agent_app.py"),
        name="HelloAgent",
        port=9999,
    )
    print(f"  Deployment ID: {result['deployment_id']}")
    print(f"  URL: {result['url']}")
    print(f"  Status: {result['status']}")

    # 查询部署列表
    print("\nListing agents...")
    deployments = await manager.list_deployments()
    for dep in deployments:
        print(f"  - {dep['deployment_id']}: {dep['status']}")

    # 获取部署详情
    deployment = await manager.get_deployment(result['deployment_id'])
    print(f"\nDeployment details: {deployment['status']}")

    # 删除部署
    print("\nDeleting deployment...")
    await manager.delete_deployment(result['deployment_id'])
    print("  Deleted!")


if __name__ == "__main__":
    asyncio.run(main())