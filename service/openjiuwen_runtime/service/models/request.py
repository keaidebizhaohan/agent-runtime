# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

"""
openjiuwen-runtime-sdk 的请求和响应模型
"""

import os
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


DEFAULT_USER_ID = "anonymous"
DEFAULT_SPACE_ID = "default"
DEFAULT_AGENT_ID = "default-agent"


def build_session_id(
    conversation_id: str,
    user_id: Optional[str] = None,
    space_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> str:
    """生成 Agent、空间、用户三层隔离的运行时会话键。"""
    normalized_agent_id = (
        agent_id or os.getenv("DEPLOYMENT_ID") or ""
    ).strip() or DEFAULT_AGENT_ID
    normalized_space_id = (space_id or "").strip() or DEFAULT_SPACE_ID
    normalized_user_id = (user_id or "").strip() or DEFAULT_USER_ID
    return (
        f"{normalized_agent_id}:{normalized_space_id}:"
        f"{normalized_user_id}:{conversation_id}"
    )


class QueryRequest(BaseModel):
    """
    Agent 查询请求模型

    属性:
        messages: 当前消息列表（非完整历史）
        conversation_id: 对话 ID（必需）
        user_id: 用户 ID
        space_id: 工作空间 ID
        stream: 是否流式输出
    """

    messages: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="当前消息列表（非完整对话历史）"
    )
    conversation_id: str = Field(
        ...,
        description="用于会话跟踪的对话 ID"
    )
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        description="用户 ID"
    )
    space_id: str = Field(
        default=DEFAULT_SPACE_ID,
        description="工作空间 ID"
    )
    stream: bool = Field(
        default=True,
        description="是否使用流式输出"
    )

    @property
    def session_id(self) -> str:
        """内部会话键；对外仍保留客户端传入的 conversation_id。"""
        return build_session_id(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            space_id=self.space_id,
        )


class ResetConversationRequest(BaseModel):
    """
    重置对话请求模型

    属性:
        conversation_id: 要重置的对话 ID（必需）
        user_id: 用户 ID（可选，用于授权）
    """

    conversation_id: str = Field(
        ...,
        description="要重置的对话 ID"
    )
    user_id: Optional[str] = Field(
        default=None,
        description="用于授权的用户 ID"
    )
    space_id: Optional[str] = Field(
        default=None,
        description="工作空间 ID"
    )

    @property
    def session_id(self) -> str:
        """使用与查询请求相同的会话隔离键。"""
        return build_session_id(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            space_id=self.space_id,
        )
