# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

"""租户隔离中间件

从 HTTP Header 或 JWT Token 中提取 user_id 和 space_id，
并将其注入到请求状态中，供后续端点使用。
"""

from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from openjiuwen_runtime.foundation.log import get_logger

logger = get_logger(__name__)

DEFAULT_USER_ID = "anonymous"
DEFAULT_SPACE_ID = "default"


def normalize_tenant_context(
    user_id: str | None,
    space_id: str | None,
) -> tuple[str, str]:
    """统一租户缺省值，使创建、查询和调用 Agent 使用同一规则。"""
    normalized_user_id = (user_id or "").strip() or DEFAULT_USER_ID
    normalized_space_id = (space_id or "").strip() or DEFAULT_SPACE_ID
    return normalized_user_id, normalized_space_id


def deployment_belongs_to_tenant(
    deployment: Any,
    user_id: str,
    space_id: str,
) -> bool:
    """判断 Agent 归属；历史 NULL 租户记录按缺省租户处理。"""
    owner = normalize_tenant_context(deployment.user_id, deployment.space_id)
    caller = normalize_tenant_context(user_id, space_id)
    return owner == caller


def require_deployment_tenant(
    deployment: Any,
    user_id: str,
    space_id: str,
) -> None:
    """拒绝当前租户访问其他租户的 Agent。"""
    if not deployment_belongs_to_tenant(deployment, user_id, space_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The Agent does not belong to the current user and space",
        )


def resolve_proxy_tenant(
    request: Request,
    service_path: str,
    proxy_body: Any,
) -> tuple[str, str, Any]:
    """
    Agent 调用支持从 Header 或 JSON 请求体取租户信息。

    Header 和 Body 同时传入时必须一致；对 query/reset 会将确认后的
    租户信息写回请求体，保证下游 session key 使用相同值。
    """
    header_user_id = request.headers.get("X-User-ID")
    header_space_id = request.headers.get("X-Space-ID")
    body_user_id = None
    body_space_id = None
    tenant_body_paths = {"query", "reset_conversation"}
    normalized_path = service_path.strip("/")

    if normalized_path in tenant_body_paths and isinstance(proxy_body, dict):
        body_user_id = proxy_body.get("user_id")
        body_space_id = proxy_body.get("space_id")
        if body_user_id is not None and not isinstance(body_user_id, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="body user_id must be a string",
            )
        if body_space_id is not None and not isinstance(body_space_id, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="body space_id must be a string",
            )

    if header_user_id is not None and body_user_id is not None:
        header_user = normalize_tenant_context(header_user_id, None)[0]
        body_user = normalize_tenant_context(body_user_id, None)[0]
        if header_user != body_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-User-ID header and body user_id must be identical",
            )
    if header_space_id is not None and body_space_id is not None:
        header_space = normalize_tenant_context(None, header_space_id)[1]
        body_space = normalize_tenant_context(None, body_space_id)[1]
        if header_space != body_space:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Space-ID header and body space_id must be identical",
            )

    user_id, space_id = normalize_tenant_context(
        body_user_id if body_user_id is not None else header_user_id,
        body_space_id if body_space_id is not None else header_space_id,
    )

    if normalized_path in tenant_body_paths and isinstance(proxy_body, dict):
        proxy_body = dict(proxy_body)
        proxy_body["user_id"] = user_id
        proxy_body["space_id"] = space_id

    return user_id, space_id, proxy_body


class TenantContextMiddleware(BaseHTTPMiddleware):
    """租户上下文中间件

    从请求头中提取 user_id 和 space_id，验证后注入到 request.state
    """

    def __init__(self, app: ASGIApp, require_tenant: bool = False):
        """
        Args:
            app: ASGI 应用
            require_tenant: 是否强制要求租户信息（默认True）
        """
        super().__init__(app)
        self.require_tenant = require_tenant

    async def dispatch(self, request: Request, call_next):
        """处理请求，提取并验证租户信息"""

        # 提取 user_id 和 space_id
        raw_user_id = request.headers.get("X-User-ID")
        raw_space_id = request.headers.get("X-Space-ID")

        # 验证租户信息
        if self.require_tenant:
            if not raw_user_id or not raw_space_id:
                logger.warning(
                    "Missing tenant context: user_id=%s, space_id=%s",
                    raw_user_id,
                    raw_space_id,
                )
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Missing tenant context: X-User-ID and X-Space-ID headers are required"}
                )

        user_id, space_id = normalize_tenant_context(raw_user_id, raw_space_id)

        # 注入到 request.state
        request.state.user_id = user_id
        request.state.space_id = space_id

        logger.debug(f"Tenant context: user_id={user_id}, space_id={space_id}")

        response = await call_next(request)
        return response


def get_tenant_context(request: Request) -> tuple[str, str]:
    """从请求中获取租户上下文

    Args:
        request: FastAPI 请求对象

    Returns:
        (user_id, space_id) 元组
    """
    user_id = getattr(request.state, "user_id", None)
    space_id = getattr(request.state, "space_id", None)
    return normalize_tenant_context(user_id, space_id)
