"""
AgentApp - Agent 应用类

提供部署 agent-studio Agent 的功能:
- Agent 实例管理
- @query 装饰器用于处理查询
- /query 和 /reset_conversation 端点
"""

import json
import asyncio
import inspect
from typing import Callable, Optional, AsyncIterator, Tuple, Dict, Any
from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse

from .base_app import BaseApp
from .middleware import Middleware, MiddlewareContext
from ..models.request import QueryRequest, ResetConversationRequest


class AgentApp(BaseApp):
    """
    openjiuwen Agent 应用类

    提供简单的 API 用于将 agent-studio Agent 部署到生产环境。

    设计原则:
    - 每个 AgentApp 持有一个 Agent 实例
    - 一个 Agent 服务所有对话
    - Agent 内部通过 conversation_id 隔离会话

    用法:
        app = AgentApp("MyAgent")

        @app.init
        async def init():
            app.agent = await load_agent_from_config(...)

        @app.query
        async def query(msgs, request):
            async for msg, last in app.agent.stream(
                messages=msgs,
                conversation_id=request.conversation_id,
            ):
                yield msg, last

        app.run(port=8090)
    """

    def __init__(
        self,
        app_name: str,
        app_description: str = "",
        version: str = "1.0.0",
        agent_config_path: str = None,
    ):
        super().__init__(app_name, app_description, version)

        # 查询钩子
        self._query_hook: Optional[Callable] = None

        # 中间件列表
        self._middlewares: list = []

        # Agent 配置路径
        self.agent_config_path = agent_config_path

        # Agent 实例 (由用户初始化)
        self.agent = None

        # 可选服务
        self.sandbox_service = None

        # 注册 Agent 特定路由
        self._register_agent_routes()

    def query(self, func: Callable) -> Callable:
        """
        查询钩子装饰器

        用法:
            @app.query
            async def query(msgs, request):
                # 处理查询
                async for msg, last in agent.stream(...):
                    yield msg, last
        """
        self._query_hook = func
        return func

    def add_middleware(self, middleware: Middleware) -> 'AgentApp':
        """
        添加中间件实例

        参数:
            middleware: 中间件实例

        返回:
            self，支持链式调用
        """
        self._middlewares.append(middleware)
        return self

    def middleware(self, middleware_class):
        """
        中间件装饰器

        用法:
            @app.middleware(MyMiddleware)
            class MyMiddleware(Middleware):
                pass

        参数:
            middleware_class: 中间件类

        返回:
            中间件实例
        """
        instance = middleware_class()
        self._middlewares.append(instance)
        return instance

    def _register_agent_routes(self):
        """注册 Agent 特定路由"""

        @self.app.post("/query")
        async def query_endpoint(query_request: QueryRequest):
            """
            查询端点 - 发送消息给 Agent 并获取流式响应

            参数:
                query_request: 包含 messages 和 conversation_id 的查询请求

            返回:
                Agent 响应的服务器发送事件 (SSE) 流
            """
            # 从请求中提取消息
            messages = query_request.messages

            # 执行查询钩子
            async def generate():
                if self._query_hook:
                    # 创建中间件上下文
                    context = MiddlewareContext()
                    processed_messages = messages
                    error_occurred = False

                    # 调用所有中间件的 before_query 方法
                    for mw in self._middlewares:
                        try:
                            processed_messages = await mw.before_query(
                                processed_messages, query_request, context
                            )
                        except Exception:
                            pass

                    try:
                        # 调用查询钩子并迭代结果
                        # 钩子应该是异步生成器函数
                        async for msg, last in self._query_hook(processed_messages, query_request):
                            # 对每个消息调用 before_response 方法
                            processed_msg = msg
                            for mw in self._middlewares:
                                try:
                                    processed_msg = await mw.before_response(
                                        processed_messages, query_request, processed_msg, context
                                    )
                                except Exception:
                                    pass
                            yield f"data: {json.dumps(processed_msg)}\n\n"

                        # 查询成功完成后调用 after_query 方法
                        for mw in self._middlewares:
                            try:
                                await mw.after_query(processed_messages, query_request, context)
                            except Exception:
                                pass
                    except Exception as e:
                        error_occurred = True
                        # 发生异常时调用 on_error 方法
                        for mw in self._middlewares:
                            try:
                                await mw.on_error(processed_messages, query_request, e, context)
                            except Exception:
                                pass
                        raise

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
            )

        @self.app.post("/reset_conversation")
        async def reset_conversation_endpoint(request: ResetConversationRequest):
            """
            重置对话端点 - 清除对话上下文

            参数:
                request: 包含 conversation_id 的重置请求

            返回:
                状态消息
            """
            # 调用 Agent 的会话清理方法
            if self.agent and hasattr(self.agent, 'clear_session'):
                await self.agent.clear_session(request.conversation_id)

            return {"status": "ok", "message": f"Conversation {request.conversation_id} reset"}

        # 更新健康检查，包含 agent_loaded 状态
        # 获取原始 /health 路由
        for route in self.app.routes:
            if hasattr(route, 'path') and route.path == "/health":
                # 存储原始端点
                original_endpoint = route.app
                break
        else:
            original_endpoint = None

        # 定义增强的健康检查
        @self.app.get("/health")
        async def health_with_agent():
            """健康检查（包含 Agent 状态）"""
            return {
                "status": "healthy",
                "app": self.app_name,
                "version": self.version,
                "agent_loaded": self.agent is not None,
            }
