"""Agent Runtime Manager Server

FastAPI 服务器，提供 Agent 部署管理 REST API（支持租户隔离）
"""

import os
import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, UploadFile, Query, status, Request
from fastapi.responses import JSONResponse

from openjiuwen_runtime.management.manager import DeploymentManager, DeployMode
from openjiuwen_runtime.management.models.enums import DeploymentType, DeploymentStatus
from openjiuwen_runtime.foundation.db.sqlite_handler import SQLiteHandler
from openjiuwen_runtime.foundation.db.mysql_handler import MySQLHandler
from openjiuwen_runtime.foundation.packaging import package_python_to_whl
from openjiuwen_runtime.foundation.port_utils import allocate_port
from openjiuwen_runtime.foundation.port_utils import is_port_available
from .config import settings
from .converter.agent_converter import AgentConverter
from .middleware.tenant import TenantContextMiddleware, get_tenant_context

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
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

# 初始化数据库组件（默认是sqlite）
DB_TYPE = os.getenv("DB_TYPE", "sqlite").lower()
logger.info(f"Using database: {DB_TYPE}")
if DB_TYPE == "sqlite":
    db_handler = SQLiteHandler("deployments.db")
elif DB_TYPE == "mysql":
    db_handler = MySQLHandler()
else:
    raise ValueError(f"Unsupported DB_TYPE: {DB_TYPE}. Use 'sqlite' or 'mysql'.")

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
    deployer_type: str = Query(default="subprocess", description="部署器类型"),
    port: int | None = Query(default=None, description="服务端口，不填则自动分配"),
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

    # 保存上传的 JSON 文件到临时目录
    content = await file.read()
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.json', delete=False) as tmp_file:
        tmp_file.write(content)
        json_file_path = tmp_file.name

    try:
        # 读取 JSON 配置
        with open(json_file_path, 'r', encoding='utf-8') as f:
            config_json = json.load(f)
        logger.info(f"Loaded JSON config: {config_json}")

        # 使用 AgentConverter 转换为 Python 文件
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = await agent_converter.convert_to_pythonDir(
                config_json=config_json,
                name=name,
                output_dir=temp_dir,
            )
            logger.info(f"Generated source directory: {source_dir}")

            whl_path = await package_python_to_whl(source_dir, package_name=name)

            # 转换 deployer_type 为 DeployMode
            deployer_type_map = {
                "subprocess": DeployMode.SUBPROCESS,
                "docker": DeployMode.DOCKER,
                "k8s": DeployMode.K8S,
            }

            mode = deployer_type_map.get(deployer_type, DeployMode.SUBPROCESS)
            logger.info(f"deployer_type: {deployer_type}, mode: {mode}")

            # 端口分配和检查
            if deployer_type == "local_subprocess":
                if port is None:
                    port = allocate_port()
                    logger.info(f"Auto-allocated port: {port}")
                elif not is_port_available(port):
                    logger.error(f"Port {port} is already in use")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Port {port} is occupied. Please use another port or leave it blank for auto-allocation."
                    )
                logger.info(f"Port: {port}")

            # 调用 Manager SDK 部署（传入租户信息）
            result = await manager.deploy_agent(
                name=name,
                version="1.0.0",
                mode=mode,
                user_id=user_id,  # 注入租户信息
                space_id=space_id,  # 注入租户信息
                whl_path=whl_path,
                port=port,
            )

            # 过滤内部实现细节，只返回用户需要的信息
            response = {
                "deployment_id": result.deployment_id,
                "type": result.deployment_type.value,
                "name": result.name,
                "status": result.deployment_status.value,
                "url": result.url,
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
                "deployment_id": dep.deployment_id,
                "name": dep.name,
                "status": dep.deployment_status.value,
                "url": dep.url,
                "port": dep.data.get("port") if dep.data else None,
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
            "deployment_id": deployment.deployment_id,
            "name": deployment.name,
            "status": deployment.deployment_status.value,
            "url": deployment.url,
            "port": deployment.data.get("port") if deployment.data else None,
            "type": deployment.deployment_type.value,
            "created_at": deployment.created_at,
            "updated_at": deployment.updated_at,
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
