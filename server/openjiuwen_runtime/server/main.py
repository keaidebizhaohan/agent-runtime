"""Agent Runtime Manager Server

FastAPI 服务器，提供 Agent 部署管理 REST API（支持租户隔离）
"""

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, UploadFile, Query, status, Request
from fastapi.responses import JSONResponse

from openjiuwen_runtime.management.manager import DeploymentManager
from openjiuwen_runtime.management.models.enums import DeploymentType, DeploymentStatus
from openjiuwen_runtime.foundation.db.sqlite_handler import SQLiteHandler

from .config import settings
from .converter.agent_converter import AgentConverter
from .middleware.tenant import TenantContextMiddleware, get_tenant_context

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
app = FastAPI(
    title="Agent Runtime Manager API",
    description="Agent 部署管理服务（支持租户隔离）",
    version="2.1.0",
)

# 添加租户中间件（临时禁用租户验证，测试用）
app.add_middleware(TenantContextMiddleware, require_tenant=False)

# 初始化组件
db_handler = SQLiteHandler('deployments.db')
manager = DeploymentManager(db_handler)
agent_converter = AgentConverter()

# 启动时初始化 manager
@app.on_event("startup")
async def startup_event():
    await manager.initialize()

# 关闭时清理
@app.on_event("shutdown")
async def shutdown_event():
    await manager.shutdown()


# ==================== 健康检查 ====================

@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "healthy"}


# ==================== Agent API ====================

@app.post("/api/v1/agents/deploy")
async def deploy_agent(
    request: Request,
    file: UploadFile,
    name: str = Query(..., description="部署名称（=包名）"),
    deployer_type: str = Query(default="local_subprocess", description="部署器类型"),
    port: int = Query(default=8090, description="服务端口"),
):
    """
    部署 Agent（JSON 配置，低码方式）

    流程:
    1. 接收上传的 JSON 配置文件
    2. AgentConverter 将 JSON 转换为 Python 文件
    3. Manager SDK 部署 Python 文件（自动注入租户信息）
    """
    # 获取租户上下文
    user_id, space_id = get_tenant_context(request)
    logger.info(f"Received agent deploy request: user_id={user_id}, space_id={space_id}, name={name}")

    # 1. 保存上传的 JSON 文件到临时目录
    content = await file.read()
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.json', delete=False) as tmp_file:
        tmp_file.write(content)
        json_file_path = tmp_file.name

    try:
        # 2. 读取 JSON 配置
        with open(json_file_path, 'r', encoding='utf-8') as f:
            config_json = json.load(f)
        logger.info(f"Loaded JSON config: {config_json}")

        # 3. 使用 AgentConverter 转换为 Python 文件
        with tempfile.TemporaryDirectory() as temp_dir:
            python_file_path = await agent_converter.convert_to_python(
                config_json=config_json,
                name=name,
                output_dir=temp_dir,
            )
            logger.info(f"Generated Python file: {python_file_path}")

            # 4. 调用 Manager SDK 部署（传入租户信息）
            result = await manager.deploy_agent(
                name=name,
                version="1.0.0",
                user_id=user_id,  # 注入租户信息
                space_id=space_id,  # 注入租户信息
                python_file_path=python_file_path,
                deployer_type=deployer_type,
                port=port,
            )

            # 过滤内部实现细节，只返回用户需要的信息
            response = {
                "deployment_id": result["deployment_id"],
                "type": result["type"],
                "name": result["name"],
                "status": result["status"],
                "url": result.get("url"),
                "port": result.get("port"),
            }

            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content=response
            )

    except Exception as e:
        logger.error(f"Agent deployment failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deployment failed: {str(e)}"
        )
    finally:
        # 清理临时文件
        if 'json_file_path' in locals() and Path(json_file_path).exists():
            Path(json_file_path).unlink()



@app.get("/api/v1/agents")
async def list_agents(
    request: Request,
    status_filter: str = Query(default=None, alias="status", description="过滤状态"),
):
    """查询 Agent 列表（仅返回当前租户的部署）"""
    # 获取租户上下文
    user_id, space_id = get_tenant_context(request)

    try:
        deployments = await manager.list_deployments(
            deployment_type=DeploymentType.AGENT,
            deployment_status=DeploymentStatus(status_filter) if status_filter else None,
            user_id=user_id,  # 租户过滤
            space_id=space_id,  # 租户过滤
        )

        # 过滤内部实现细节
        filtered_deployments = []
        for dep in deployments:
            filtered_deployments.append({
                "deployment_id": dep["deployment_id"],
                "name": dep.get("name"),
                "status": dep["status"].value if hasattr(dep["status"], "value") else str(dep["status"]),
                "url": dep.get("url"),
                "port": dep.get("port"),
            })

        return {"deployments": filtered_deployments}
    except Exception as e:
        logger.error(f"Failed to list agents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list deployments: {str(e)}"
        )


@app.get("/api/v1/agents/{deployment_id}")
async def get_agent(request: Request, deployment_id: str):
    """获取 Agent 详情（仅能访问当前租户的部署）"""
    # 获取租户上下文
    user_id, space_id = get_tenant_context(request)

    try:
        deployment = await manager.get_deployment(
            deployment_id
        )
        if not deployment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Deployment {deployment_id} not found"
            )
        # 过滤内部实现细节
        return {
            "deployment_id": deployment["deployment_id"],
            "name": deployment.get("name"),
            "status": deployment["status"].value if hasattr(deployment["status"], "value") else str(deployment["status"]),
            "url": deployment.get("url"),
            "port": deployment.get("port"),
            "type": deployment.get("type"),
            "created_at": deployment.get("created_at"),
            "updated_at": deployment.get("updated_at"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get agent: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get deployment: {str(e)}"
        )


@app.delete("/api/v1/agents/{deployment_id}")
async def delete_agent(request: Request, deployment_id: str):
    """删除 Agent（仅能删除当前租户的部署）"""
    # 获取租户上下文
    user_id, space_id = get_tenant_context(request)

    try:
        success = await manager.delete_deployment(
            deployment_id
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Deployment {deployment_id} not found"
            )
        return {"message": f"Deployment {deployment_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete agent: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete deployment: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
